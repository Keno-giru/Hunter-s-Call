# Reviewing eval/real in CVAT (self-hosted, private)

CVAT runs on this PC in Docker; no frame leaves the machine. One CVAT task per clip. The converter is
`eval/cvat.py` (round trip tested: `tests/py/test_cvat.py`).

## 1. Start CVAT (once)

Needs Docker Desktop running and about 6 GB free on C: for the containers.

```bash
git clone https://github.com/cvat-ai/cvat <your cvat folder>
```

```bash
cd <your cvat folder> && docker compose up -d
```

Create your login (you choose the password; it stays local):

```bash
docker exec -it cvat_server bash -ic "python3 ~/manage.py createsuperuser"
```

Open http://localhost:8080 and sign in. Stop it later with `docker compose down` in the cvat folder
(your work is kept in Docker volumes).

## Quick path (does steps 2, 3 and 5 for you)

```bash
python eval/cvat.py setup
```

creates the project, the label spec, one task per clip with its frames, and imports the pre-labels. After
reviewing (step 4):

```bash
python eval/cvat.py pull
```

downloads every task and imports it into eval/real, then prints QA. Both ask for your CVAT username and
password in the terminal (hidden, never stored). Re-running `setup` skips what already exists.

The manual steps below do the same through the CVAT web UI.

## 2. Project and labels (once)

```bash
python eval/cvat.py labels
```

In CVAT: Projects > + > name `Galileo eval-real` > Labels > **Raw** > paste the contents of
`eval/cvat/labels.json` > Done > Submit.

Labels: `player` and `goalkeeper` boxes (team home/away, id, jersey), `referee` box (id), `ball` box,
`landmark` points (attribute `kp` = pitch landmark id), and the image tag `reviewed`.

## 3. One task per clip

```bash
python eval/cvat.py export
```

For each clip (`gsr-SNGS-129`, `gsr-SNGS-137`, `gsr-SNGS-143`, `gsr-SNGS-190`, `gsr-SNGS-196`):

1. In the project: + > Create a new task. Name = the clip id.
2. Select files > My computer > all `.jpg` files in `eval/real/<clip>/frames/`. Advanced: sorting **Lexicographical**.
3. Submit, open the task, Actions > **Upload annotations** > format **CVAT 1.1** > `eval/cvat/<clip>/annotations.zip`.

## 4. Review (every frame)

Open the job (annotation mode, not track mode). For each frame:

- boxes: right class (keepers are sometimes labelled `player` in the source), right team, tight fit,
  missing players or ball added, spectators or coaches removed
- identity clips (`gsr-SNGS-137`, `gsr-SNGS-196`): the same person keeps the same `id` throughout
- landmarks: each point on its pitch marking; delete one you cannot see; keep at least 6 per frame
- Save often (Ctrl+S)

When you have checked **every** frame of a job: Menu (top left) > **Finish the job** (state "completed").
`pull` then counts all frames of that job as reviewed. Halfway through a job, you can instead mark single
frames: left toolbar > tag icon (Setup tag) > label `reviewed` > Tag. The exam cannot be frozen until all
461 frames are reviewed.

## 5. Back into Galileo

Actions > **Export task dataset** > format **CVAT for images 1.1**, Save images **off** > download the zip, then:

```bash
python eval/cvat.py import gsr-SNGS-129 <downloads folder>/<export>.zip
```

It refuses partial exports and video-mode (track) exports, writes nothing in that case, and prints the
clip's QA. Repeat per clip; you can import again after more review.

## 6. Freeze

When every frame is reviewed and `python eval/realset.py qa` passes:

```bash
python eval/realset.py freeze --reviewer Keno
```

```bash
python eval/run.py --track T1
```
