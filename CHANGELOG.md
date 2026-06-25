# Changelog

## Branch strategy

| Branch | Tag | Role |
|--------|-----|------|
| `main` | `v1.0.0` | **Production** — what's deployed on Render (`nerf.mattbouchard.com`). RunPod GPU backend, landing page, `/sample`. Safe rollback target. |
| `devel` | `v2.0.0-dev` | **Development** — v2 features (WebGL `/viewer`, World Labs scaffold, SplatCapture iOS sources, job TODOs). Merge to `main` when ready to deploy. |

**Rollback:** redeploy or reset to `main` / tag `v1.0.0`. Render auto-deploy tracks `main` unless you change the branch in the dashboard.

---

## v2.0.0-dev (devel) — unreleased

- `GET /viewer` — mobile WebGL Gaussian-splat viewer (gsplat.js) for in-app preview
- World Labs backend scaffold (`worldlabs_backend.py` + tests + reference solution)
- `SplatCapture-iOS/` — SwiftUI capture + upload + poll + WebView viewer
- Hero splat images in `assets/`
- `TODO.md` — persistent job state, client poll hardening
- Landing page tweaks for worldlabs mode

## v1.0.0 (main) — production baseline

- FastAPI 202 + poll API (`/upload`, `/nerfify`, `/jobs`, `/result`)
- RunPod GPU worker integration (COLMAP + splatfacto)
- R2 storage, custom domain, landing page, `/sample` demo splat
