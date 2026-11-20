# Friends' reports, photos and public comments — design

Date: 2026-11-20 · Status: final draft — open questions answered; awaiting owner approval

## Intent

Wild Ice is a personal map of skateable wild ice in Southcentral Alaska. Its owner
wants trusted **friends** to send their own on-the-ice reports and photos, and **anyone**
to leave public comments on a lake, without handing anyone the owner's GitHub key and
without strangers being able to spoil the data.

Why: friends' reports are more real observations for the ice model (the main point),
good photos make each lake's page more useful, and comments let a small, niche skating
community share practical tips.

## Goals

1. **Friends report** a lake (condition + ice-quality grade + optional photo + note);
   reports feed the ice model the same way the owner's do today, with no approval step.
2. **Ice-quality grade** on the owner's scale **A+ … F-** is a new report field, for the
   owner and friends alike.
3. **Photos** serve as evidence (their GPS location checks which lake the reporter was
   on) and, once the owner approves one, as a **featured photo** on that lake's public page.
4. **Public comments** on a lake: anyone can read them; comments from people without an
   invite wait for owner approval; invited friends' comments appear immediately.
5. **Per-friend access the owner can switch off**, one person at a time.
6. **Zero cost**, consistent with the rest of the project. Owner's standing rule:
   **default to the free option at every opportunity**; no payment card on any account.

## Non-goals

- Accounts with passwords, email sign-up, or profiles.
- Comments as model input. A comment never changes a lake's label or confidence.
- A general-purpose photo gallery; only featured photos are shown, a few per lake.
- Replacing the daily GitHub Actions job or the static GitHub Pages site.

## Anti-goals (failure even if it "works")

- **The owner's phone dings more.** No notification per comment, photo or report. The
  only additions: one line inside the existing morning ice alert when it goes out anyway,
  and at most **one reminder a week**, only if something has waited **more than 7 days**.
- **A stranger can make thin ice look good.** Only invited reporters influence the model.
- **Public photos reveal where someone stood or when.** Featured copies have all metadata
  (GPS, time, device) removed.
- **Secrets on phones.** No GitHub token, ntfy topic or admin key ever reaches a
  friend's browser.

## Constraints

- The repo `JustMoosinAround/wild-ice` is **public**: anything committed is world-readable.
  Friends' identities and original photos must not be committed.
- The site is static (GitHub Pages); the daily job runs in GitHub Actions and reads
  `ratings/*.json` (see `wildice/reports.py`).
- Phones often strip GPS from photos uploaded through a web page (iOS photo picker,
  Android 10+ photo picker). Verification must work when GPS is missing.
- Standing rules: never log or commit secrets or ntfy topic names; never commit personal
  skating data.

## Approaches considered

1. **Cloudflare Worker + D1 + Workers KV + Turnstile** — *chosen* (R2 was planned for
   photos but needs a card; owner chose the free no-card KV store instead). One free Cloudflare account. A
   small Worker holds the secrets, checks invites, strips photo metadata, stores photos
   privately (KV) and comments (D1), and writes friends' reports into the repo with a
   narrowly scoped GitHub token. Turnstile (free) stops bots on stranger comments. No
   pausing, generous free limits (R2 10 GB, Workers 100k requests/day).
2. **Supabase** — free hosted database with email-link logins and storage. Rejected: the
   spam check and photo handling still need custom functions, friends must sign in by
   email each time, and free projects pause when idle.
3. **GitHub only** (giscus comments + issue forms) — rejected: everyone needs a GitHub
   account, comments can't be held for approval, and GitHub strips GPS from uploads.

Owner picked **Cloudflare** for one free account, the best built-in spam protection,
and keeping secrets off phones.

## Decided (by the owner, in conversation)

- Friends' reports are mainly **model input**; also show **featured photos** publicly.
- Photo **GPS is wanted** to verify which lake.
- **Comments: public and moderated.**
- **Minimal notifications**: review page instead of pushes; one line in the morning alert;
  weekly reminder only for items waiting > 7 days.
- **Ice-quality grade A+ … F-** is part of a report.
- **Cloudflare** as the platform.

## Proposed by the designer (owner may correct)

- **Invites.** Each friend gets a personal invite link (`…/#invite=<code>`). Opening it
  stores a random device key in that browser; the Worker keeps the mapping key → friend.
  The owner can revoke a friend (all their devices) from the review page. The owner gets
  an admin invite and also reports through the Worker, so the GitHub token in the browser
  (`ratings.js` today) goes away.
- **Display names.** Friends choose a display name shown on their comments and featured
  photo credits. Reports committed to the repo carry only a pseudonymous `reporter`
  (e.g. `f7`), never a name; the name ↔ id mapping stays in D1.
- **Anyone can comment** with a name, no invite. Plain text only, no links, max ~500
  characters, Turnstile check, rate limit (e.g. 3 per hour per device/IP). Held for
  approval. Invited friends' comments publish immediately.
- **Moderation lives on a review page** on the map (`#review`, admin key required) listing
  waiting comments and photos, each with Approve / Reject; also lists friends with Revoke.
- **Featured photos**: the owner approves a photo to feature it; the Worker serves the
  metadata-free copy from KV. Up to ~6 featured per lake, newest first.
- **Lake verification.** If the photo's GPS survives upload, it must fall within ~300 m of
  the chosen lake's outline, else the report is stored but marked `unverified` and the
  model ignores it. If GPS is missing, the form offers one-tap "use my current location"
  for on-the-spot reports; reports with neither are accepted as `unverified_location`
  and *are* used (friends are trusted), but the flag is kept for later backtests.
- **Grade → model (owner: every grade means skateable).** A graded report counts as
  skateable ice for the ice estimate. The grade sets quality: **A+ … C-** shows as good
  skating and can trigger the morning alert; **D+ … F-** shows as skateable but rough, no
  alert, grade displayed. Grades go with Skateable (and Rough); Open water / Snow on ice
  take no grade. The cutoff lives in `config.yaml`.
- **Several reporters, one lake.** The newest report wins (as today); the reason line names
  how many reports a lake had in the last week ("3 reports this week").
- **Owner's morning alert** gets one line ("3 comments, 2 photos waiting") when there is
  anything waiting and the alert goes out anyway. The daily job asks the Worker for the
  count using an admin token stored as a GitHub Actions secret.
- **Weekly reminder**: a Worker cron trigger, once a week, sends one ntfy message to the
  owner only if an item has waited > 7 days.
- **Report storage (designer's call after review).** Friends' and the owner's reports
  live in D1, not the public repo; the daily job fetches them from the Worker with the
  admin token. Publicly a lake shows only "reported skateable Nov 4 (B+)" and a weekly
  count: no names, reporter ids or notes, so no one can trace where a friend skates.
  Notes appear only on the review page. Featured photo ids are unrelated to stored ids.
  With reports off the repo, the Worker needs no GitHub token at all.
- **Invites (designer's call).** Each invite link works once, on one device; a new phone
  needs a new invite, created on the review page. A forwarded link can't be reused.
- **Revoke (designer's call)** cuts access only; past reports, comments and photos stay
  unless removed one by one on the review page.
- **Owner's reports are always trusted** (no lake check exclusion), as today.
- **Pins and hides** move to the Worker (admin only), so the GitHub token leaves the
  browser entirely. Reports made without signal still queue on the phone (photo
  included) and resend with an idempotency key so nothing is saved twice.

## Open questions for the owner

1. **Worth-the-drive cutoff.** Owner confirmed every grade A+ … F- means skateable
   ("F = skateable but awful"); the grade is quality, not safety. Proposed cutoff: A+ … C-
   = good skating (can alert), D+ … F- = skateable but rough (no alert, grade shown).
   **Owner confirmed C-.**
2. **No card: R2 is out.** Owner chose the free, no-card route. Photos go to **Workers
   KV** (free: 1 GB total, 25 MB per value, ~1,000 writes/day): featured copies resized to
   ~1600 px with metadata stripped, originals kept ~3 weeks for lake checks and review,
   then deleted. Workers, D1, Turnstile and cron triggers are all on the free plan with no
   card. Deploys use a scoped Cloudflare API token supplied through the environment's
   secure credential form, never pasted into chat.

## Out of scope for this build, noted

- Using grades in the backtest/tuning beyond storing them.
- Showing friends' (non-featured) photos to the owner beyond the review page.
- Rotten-ice spring rule (separate to-do).

## Left to the builder

- Worker routing, D1 schema, KV key layout, EXIF parsing/stripping library (must run in
  Workers), image resizing for featured copies.
- Deploy method (wrangler from a GitHub Action with a Cloudflare API token secret, or the
  owner running one command), and step-by-step setup notes for the owner.
- Exact rate limits, size limits (photos ≤ ~15 MB in, featured copy ~1600 px), and the
  look of the report form, comment list, featured photos and review page — following the
  map's existing style (`site/style.css`).
- Tests: Worker unit tests (invite, verification, moderation, metadata stripping) and the
  daily job reading the new report fields.
