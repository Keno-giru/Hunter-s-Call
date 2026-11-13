// Galileo hub - perspective warp of the shared ground layer onto match footage (track A1).
//
// Every overlay in the hub is painted once, in pitch metres, onto ctx.ground.overlay (core.js). The
// 3D pitch drapes that canvas as a texture and the 2D board draws it as its background. This module
// is the third consumer: it projects the same canvas through the camera homography so drawings,
// unit lines, pitch control, Voronoi cells and heatmaps land on the real grass in the video.
//
// It is an INVERSE warp: for each screen pixel we ask which ground pixel it came from. That is what
// makes it safe near the horizon (pixels whose ray passes behind the camera are simply discarded)
// and exact everywhere else. WebGL does it in one draw call; without WebGL a triangle mesh on a 2D
// canvas gets close enough, at a cost that still holds 60 fps on a mid-range laptop.
//
// Coordinates, in order: pitch metres -> ground canvas px (affine, from ctx.ground) -> video px
// (the homography H) -> canvas CSS px (the letterbox fit of the video inside the stage).

// ------------------------------------------------------------------ 3x3 matrices (row-major, node-testable)

export function mat3mul(A, B) {
  const C = new Array(9);
  for (let r = 0; r < 3; r++) for (let c = 0; c < 3; c++) C[r * 3 + c] = A[r * 3] * B[c] + A[r * 3 + 1] * B[3 + c] + A[r * 3 + 2] * B[6 + c];
  return C;
}

export function mat3inv(M) {
  const [a, b, c, d, e, f, g, h, i] = M;
  const A = e * i - f * h, B = -(d * i - f * g), C = d * h - e * g;
  const det = a * A + b * B + c * C;
  if (!(Math.abs(det) > 1e-300)) return null;
  const out = [A, -(b * i - c * h), b * f - c * e, B, a * i - c * g, -(a * f - c * d), C, -(a * h - b * g), a * e - b * d].map((v) => v / det);
  return out.every(Number.isFinite) ? out : null;
}

export function mat3apply(M, x, y, out) {
  const w = M[6] * x + M[7] * y + M[8];
  if (!(Math.abs(w) > 1e-12)) return false;
  out[0] = (M[0] * x + M[1] * y + M[2]) / w;
  out[1] = (M[3] * x + M[4] * y + M[5]) / w;
  return Number.isFinite(out[0]) && Number.isFinite(out[1]);
}

/** Ground canvas pixels -> pitch metres. ground: { scale, margin } plus the pitch size. */
export function groundToPitch({ scale, margin }, pitch) {
  return [1 / scale, 0, -(pitch.L / 2 + margin), 0, -1 / scale, pitch.W / 2 + margin, 0, 0, 1];
}

/**
 * The full chain, ground canvas px -> canvas CSS px.
 * H: pitch metres -> video px. lay: { ox, oy, s } placing the video inside the stage in CSS px.
 */
export function groundToScreen(H, ground, pitch, lay) {
  const fit = [lay.s, 0, lay.ox, 0, lay.s, lay.oy, 0, 0, 1];
  return mat3mul(fit, mat3mul(H, groundToPitch(ground, pitch)));
}

// ------------------------------------------------------------------ WebGL path

const VERT = `attribute vec2 a_pos; uniform vec2 u_size; varying vec2 v_pix;
void main() { v_pix = vec2((a_pos.x * 0.5 + 0.5) * u_size.x, (0.5 - a_pos.y * 0.5) * u_size.y); gl_Position = vec4(a_pos, 0.0, 1.0); }`;

// u_inv maps a screen pixel back to a ground-canvas pixel. u_wsign keeps the half of the projective
// map the pitch actually lives in: the other half is the world folded back through the horizon.
const FRAG = `precision highp float;
varying vec2 v_pix; uniform mat3 u_inv; uniform vec2 u_tex; uniform float u_wsign; uniform sampler2D u_src; uniform float u_alpha;
void main() {
  vec3 g = u_inv * vec3(v_pix, 1.0);
  if (g.z * u_wsign <= 0.0) discard;
  vec2 uv = (g.xy / g.z) / u_tex;
  if (uv.x < 0.0 || uv.y < 0.0 || uv.x > 1.0 || uv.y > 1.0) discard;
  vec4 c = texture2D(u_src, uv);
  gl_FragColor = c * u_alpha;
}`;

function compile(gl, type, src) {
  const sh = gl.createShader(type);
  gl.shaderSource(sh, src); gl.compileShader(sh);
  if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) { console.warn("[warp] shader", gl.getShaderInfoLog(sh)); gl.deleteShader(sh); return null; }
  return sh;
}

function createGl(canvas) {
  const opts = { alpha: true, premultipliedAlpha: true, antialias: false, depth: false, stencil: false, preserveDrawingBuffer: false };
  const gl = canvas.getContext("webgl2", opts) || canvas.getContext("webgl", opts);
  if (!gl) return null;
  const vs = compile(gl, gl.VERTEX_SHADER, VERT), fs = compile(gl, gl.FRAGMENT_SHADER, FRAG);
  if (!vs || !fs) return null;
  const prog = gl.createProgram();
  gl.attachShader(prog, vs); gl.attachShader(prog, fs); gl.linkProgram(prog);
  if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) { console.warn("[warp] link", gl.getProgramInfoLog(prog)); return null; }
  gl.useProgram(prog);
  const buf = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, buf);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);   // one big triangle
  const loc = gl.getAttribLocation(prog, "a_pos");
  gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
  const tex = gl.createTexture();
  gl.bindTexture(gl.TEXTURE_2D, tex);
  for (const [k, v] of [["TEXTURE_MIN_FILTER", "LINEAR"], ["TEXTURE_MAG_FILTER", "LINEAR"], ["TEXTURE_WRAP_S", "CLAMP_TO_EDGE"], ["TEXTURE_WRAP_T", "CLAMP_TO_EDGE"]]) {
    gl.texParameteri(gl.TEXTURE_2D, gl[k], gl[v]);
  }
  gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, true);
  gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
  gl.enable(gl.BLEND);
  gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
  return {
    gl, prog, tex,
    u: { inv: gl.getUniformLocation(prog, "u_inv"), size: gl.getUniformLocation(prog, "u_size"), tex: gl.getUniformLocation(prog, "u_tex"), wsign: gl.getUniformLocation(prog, "u_wsign"), alpha: gl.getUniformLocation(prog, "u_alpha"), src: gl.getUniformLocation(prog, "u_src") },
  };
}

// ------------------------------------------------------------------ 2D mesh fallback

const MESH_COLS = 18, MESH_ROWS = 12;

/**
 * Draws the source canvas through M with a triangle mesh: inside one small cell a projective map is
 * close enough to the affine map a 2D canvas can do. Cells whose corners fold behind the horizon are
 * dropped, so the pitch simply ends where the camera stops seeing it.
 */
export function drawMesh(g, src, M, { cols = MESH_COLS, rows = MESH_ROWS, bleed = 0.75 } = {}) {
  const W = src.width, H = src.height, P = [0, 0];
  const px = new Float64Array((cols + 1) * (rows + 1) * 2), okFlag = new Uint8Array((cols + 1) * (rows + 1));
  for (let j = 0; j <= rows; j++) {
    for (let i = 0; i <= cols; i++) {
      const k = j * (cols + 1) + i;
      const sx = (i * W) / cols, sy = (j * H) / rows;
      const w = M[6] * sx + M[7] * sy + M[8];
      okFlag[k] = w > 0 && mat3apply(M, sx, sy, P) ? 1 : 0;      // w > 0: the half the pitch lives in
      px[k * 2] = P[0]; px[k * 2 + 1] = P[1];
    }
  }
  let drawn = 0;
  const tri = (a, b, c) => {
    const [sx0, sy0] = a.s, [sx1, sy1] = b.s, [sx2, sy2] = c.s;
    const d = (sx1 - sx0) * (sy2 - sy0) - (sx2 - sx0) * (sy1 - sy0);
    if (!(Math.abs(d) > 1e-9)) return;
    // affine A with A(s_i) = d_i, solved from the two edge vectors
    const m11 = ((b.d[0] - a.d[0]) * (sy2 - sy0) - (c.d[0] - a.d[0]) * (sy1 - sy0)) / d;
    const m12 = ((c.d[0] - a.d[0]) * (sx1 - sx0) - (b.d[0] - a.d[0]) * (sx2 - sx0)) / d;
    const m21 = ((b.d[1] - a.d[1]) * (sy2 - sy0) - (c.d[1] - a.d[1]) * (sy1 - sy0)) / d;
    const m22 = ((c.d[1] - a.d[1]) * (sx1 - sx0) - (b.d[1] - a.d[1]) * (sx2 - sx0)) / d;
    const dx = a.d[0] - m11 * sx0 - m12 * sy0, dy = a.d[1] - m21 * sx0 - m22 * sy0;
    if (![m11, m12, m21, m22, dx, dy].every(Number.isFinite)) return;
    // grow the triangle a hair about its centroid so neighbouring cells meet without a seam
    const gx = (a.d[0] + b.d[0] + c.d[0]) / 3, gy = (a.d[1] + b.d[1] + c.d[1]) / 3;
    const grow = (p) => [gx + (p[0] - gx) * (1 + bleed / Math.max(1, Math.hypot(p[0] - gx, p[1] - gy))), gy + (p[1] - gy) * (1 + bleed / Math.max(1, Math.hypot(p[0] - gx, p[1] - gy)))];
    const A2 = grow(a.d), B2 = grow(b.d), C2 = grow(c.d);
    g.save();
    g.beginPath(); g.moveTo(A2[0], A2[1]); g.lineTo(B2[0], B2[1]); g.lineTo(C2[0], C2[1]); g.closePath(); g.clip();
    g.setTransform(m11, m21, m12, m22, dx, dy);
    g.drawImage(src, 0, 0);
    g.restore();
    drawn++;
  };
  const node = (i, j) => {
    const k = j * (cols + 1) + i;
    return okFlag[k] ? { s: [(i * W) / cols, (j * H) / rows], d: [px[k * 2], px[k * 2 + 1]] } : null;
  };
  const base = g.getTransform ? g.getTransform() : null;
  for (let j = 0; j < rows; j++) {
    for (let i = 0; i < cols; i++) {
      const a = node(i, j), b = node(i + 1, j), c = node(i + 1, j + 1), d = node(i, j + 1);
      if (a && b && c) tri(a, b, c);
      if (a && c && d) tri(a, c, d);
      if (base) g.setTransform(base);
    }
  }
  return drawn;
}

// ------------------------------------------------------------------ the warper

/**
 * createWarper() -> { el, mode, resize, draw, clear, dispose }
 * `el` is a canvas to place under the vector overlay. `draw` returns true when it painted.
 */
export function createWarper() {
  const el = document.createElement("canvas");
  el.setAttribute("aria-hidden", "true");
  let ctxGl = null, ctx2d = null, mode = "none", srcVersion = -1, lost = false, size = { w: 0, h: 0 };

  el.addEventListener("webglcontextlost", (e) => { e.preventDefault(); lost = true; mode = "2d"; ctxGl = null; }, false);

  function ensure() {
    if (mode !== "none" || lost) return mode;
    ctxGl = createGl(el);
    if (ctxGl) { mode = "gl"; return mode; }
    ctx2d = el.getContext("2d");
    mode = ctx2d ? "2d" : "none";
    return mode;
  }

  function resize(wCss, hCss, dpr) {
    const w = Math.max(1, Math.round(wCss * dpr)), h = Math.max(1, Math.round(hCss * dpr));
    if (w === size.w && h === size.h) return false;
    size = { w, h, wCss, hCss, dpr };
    el.width = w; el.height = h;
    el.style.width = `${wCss}px`; el.style.height = `${hCss}px`;
    srcVersion = -1;
    return true;
  }

  function clear() {
    if (mode === "gl" && ctxGl) { const gl = ctxGl.gl; gl.disable(gl.SCISSOR_TEST); gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT); }
    else if (ctx2d) { ctx2d.setTransform(1, 0, 0, 1, 0, 0); ctx2d.clearRect(0, 0, el.width, el.height); }
  }

  /**
   * draw({ src, M, version, alpha, clip }) where M maps source-canvas px -> canvas CSS px and
   * `version` lets the texture upload be skipped when the source has not been repainted.
   */
  function draw({ src, M, version = null, alpha = 1, clip = null }) {
    if (!src || !M || !size.w) return false;
    if (ensure() === "none") return false;
    const inv = mat3inv(M);
    if (!inv) { clear(); return false; }
    if (mode === "gl") {
      const { gl, u, tex } = ctxGl;
      gl.viewport(0, 0, size.w, size.h);
      gl.disable(gl.SCISSOR_TEST);
      gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT);
      if (clip) {                                   // keep the warp inside the video, out of the letterbox bars
        const d = size.dpr, x0 = Math.floor(clip.x * d), y0 = Math.floor(size.h - (clip.y + clip.h) * d);
        gl.enable(gl.SCISSOR_TEST);
        gl.scissor(Math.max(0, x0), Math.max(0, y0), Math.max(0, Math.ceil(clip.w * d)), Math.max(0, Math.ceil(clip.h * d)));
      }
      gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, tex);
      if (version === null || version !== srcVersion) {
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, src);
        srcVersion = version;
      }
      gl.uniform1i(u.src, 0);
      gl.uniform2f(u.size, size.wCss, size.hCss);
      gl.uniform2f(u.tex, src.width, src.height);
      gl.uniform1f(u.alpha, alpha);
      gl.uniform1f(u.wsign, Math.sign(M[8]) || 1);
      // GLSL mat3 is column-major; M is row-major
      gl.uniformMatrix3fv(u.inv, false, new Float32Array([inv[0], inv[3], inv[6], inv[1], inv[4], inv[7], inv[2], inv[5], inv[8]]));
      gl.drawArrays(gl.TRIANGLES, 0, 3);
      return true;
    }
    const g = ctx2d;
    g.setTransform(1, 0, 0, 1, 0, 0);
    g.clearRect(0, 0, el.width, el.height);
    g.setTransform(size.dpr, 0, 0, size.dpr, 0, 0);
    g.globalAlpha = alpha;
    g.imageSmoothingEnabled = true;
    if (clip) { g.save(); g.beginPath(); g.rect(clip.x, clip.y, clip.w, clip.h); g.clip(); }
    const n = drawMesh(g, src, M);
    if (clip) { g.setTransform(size.dpr, 0, 0, size.dpr, 0, 0); g.restore(); }
    g.globalAlpha = 1;
    return n > 0;
  }

  return {
    el,
    get mode() { return mode === "none" ? ensure() : mode; },
    resize, draw, clear,
    dispose() {
      if (ctxGl) { const e = ctxGl.gl.getExtension("WEBGL_lose_context"); if (e) e.loseContext(); }
      ctxGl = null; ctx2d = null; mode = "none"; el.remove();
    },
  };
}
