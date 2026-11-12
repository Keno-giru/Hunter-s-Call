---
name: galileo-provider-audit
description: Audits a football data provider or dataset for Galileo (coverage, licence and attribution, access, cost, rate limits, update cadence, field-level quality, what it withholds) and writes one verified entry into DATA_SOURCE_REGISTRY.md. Use when evaluating, adding, renewing or doubting any data source, API, dataset or footage source.
---

# Galileo Provider Audit

One provider gives one registry entry with every claim verified live. This skill is a thin wrapper that fixes the output schema and chains existing skills: knowledge-edge-map → second-source → revelations-1-16 → claims-ledger.

## Rules

- **Live facts only.** Prices, rate limits, plan contents, licence terms and coverage change. Every value is fetched now from the provider's own pages or docs, with URL and retrieval date. Memory and training data are not a source. Use knowledge-edge-map to route.
- **Primary first.** Use the provider's docs, licence file, terms and pricing page. Third-party blog posts can only corroborate.
- **No sign-ups, no keys.** The audit uses public pages. If a fact needs an account, record it as `unknown — requires account` and put it on Keno's question list.
- **Licence before ingestion.** An entry with `licence_status = unclear` blocks ingestion and redistribution.
- **GDPR.** Note whether the source carries health or injury detail. Galileo stores availability status only.

## Steps

1. **Scope.** Name the provider and product, and which Galileo needs it serves: fixtures, results, events, lineups, formations, availability, tracking, video, odds, news.
2. **Fetch.** Pull docs, the licence or terms page and the pricing page. Record URL and retrieval date for each.
3. **Fill the entry** (template below). Tag every value `[sourced: url]`, `[inferred]` or `[unknown]` (claims-ledger).
4. **Withholding pass** (revelations-1-16). Check what the source should disclose but doesn't: competitions missing from the coverage list, seasons with gaps, fields present in the sample but absent in the free tier, undocumented update latency, silent historical revisions, missing pitch dimensions (common in event data), missing confidence or quality flags.
5. **Sample test.** If a free sample exists and the workspace can reach it (GitHub-hosted samples usually can), load one match, run the galileo-data-normalisation checks, and report pass/fail per check.
6. **Cadence.** Propose how often to refresh this source (historical weekly, fixtures daily, availability pre-match) and what Watchtower should diff.
7. **Verdict.** `adopt-now | adopt-later | sample-only | reject`, with the reason and the gaps another source must fill.

## Registry entry template

```markdown
### <Provider — Product>   (audited YYYY-MM-DD by <Claude|ChatGPT>, reviewed by <other>)
| Field | Value | Tag |
|---|---|---|
| Serves | events / lineups / tracking / … | |
| Competitions & seasons | | [sourced: url] |
| Access | open download / API key / account + NDA | |
| Cost | free / tier prices (date-stamped) | |
| Rate limits | | |
| Update cadence & latency | e.g. injuries ~4 h, lineups ~20–40 min pre-KO | |
| Licence & attribution | name, link, redistribution allowed? | |
| licence_status | clear / conditional / unclear | |
| Personal / health data | none / availability / medical detail | |
| Format & kloppy support | | |
| Coordinate system & pitch dims | | |
| IDs offered | provider IDs, external IDs (e.g. Transfermarkt) | |
| Sample test | pass/fail per normalisation check | |
| Withheld / gaps | | |
| Proposed refresh cadence | | |
| Verdict | adopt-now / adopt-later / sample-only / reject | |
```

## Hand-off

The entry goes into `DATA_SOURCE_REGISTRY.md`. Open questions go to the decision list. The other model reviews every entry before adoption, with a fresh live check of at least the licence and cost rows.

## Works with

scout-swarm (audit many providers in parallel, one scout per provider), knowledge-edge-map, second-source, revelations-1-16, claims-ledger, watchtower (freshness monitoring after adoption), galileo-data-normalisation (sample test).
