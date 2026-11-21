# Ice Log setup

The Ice Log runs on a free Cloudflare Worker (`worker/`). Everything here is on
Cloudflare's free plan; no payment card is needed. Steps marked **you** need the
owner; the rest Claude can do in a session once it has the API token.

## 1. Cloudflare account (you)

Sign up at dash.cloudflare.com/sign-up with email and password. Skip any plan or card
prompts; the free plan is all the Ice Log uses.

## 2. API token for deploying (you)

In the Cloudflare dashboard: **My Profile → API Tokens → Create Token → Create Custom
Token**. Name it `wild-ice deploy` and give it these permissions, for your account only:

| Scope | Permission | Access |
|---|---|---|
| Account | Workers Scripts | Edit |
| Account | D1 | Edit |
| Account | Workers KV Storage | Edit |
| Account | Turnstile | Edit |
| Account | Account Settings | Read |

Create it, then give it to Claude **only through the secure credential form** Claude
opens for `api.cloudflare.com` — never paste it into chat. You can delete the token in
the same dashboard page once the Ice Log is live.

## 3. Deploy (Claude)

From `worker/`:

1. `npx wrangler d1 create wild-ice` and `npx wrangler kv namespace create PHOTOS`;
   put the two ids into `wrangler.toml`.
2. `npx wrangler d1 migrations apply wild-ice --remote`.
3. Create a Turnstile widget (Managed) for `justmoosinaround.github.io`; its site key
   goes in `site/config.js` (public), its secret into the worker as `TURNSTILE_SECRET`.
4. Generate `BOOTSTRAP_TOKEN` and `SERVICE_TOKEN` locally and set both with
   `npx wrangler secret put` (values are never printed or committed).
5. `npx wrangler deploy`; put the worker's address in `site/config.js` as `WORKER_URL`.
6. Call `/api/bootstrap` once to make **your** single-use owner invite link.

## 4. Your phone (you)

Open the owner invite link on your phone and tap **Join**. That phone is now the owner:
it sees **Review** in the header and Pin/Hide on lakes. Invite friends from **Review →
New invite**; each link works once, on one phone.

## 5. Connect the daily job (you)

In GitHub: **Settings → Secrets and variables → Actions → New repository secret**:

- `ICELOG_URL` — the worker address (same as `WORKER_URL` in `site/config.js`).
- `ICELOG_TOKEN` — the `SERVICE_TOKEN`. Claude leaves it in a file in the session's
  scratchpad for you to copy (not in chat), and deletes the file once you've saved it.

## 6. Weekly reminder (you, optional)

In the Cloudflare dashboard: **Workers & Pages → wild-ice → Settings → Variables and
Secrets → Add → Secret**, name `NTFY_TOPIC`, value: the ntfy topic you want the
once-a-week "items waiting" reminder on (for example your ops topic). Claude never needs
to see it. Without it, there is simply no reminder.

## Checking it works

- Log a test report on your phone, then run the daily workflow (**Actions → daily → Run
  workflow**). Its log shows `ice log: 1 report(s) …`, and the lake's description starts
  with `You reported …`.
- A comment from a browser without an invite says "It will appear once it's checked"
  and shows up under **Review**.

## Free-plan limits (for reference)

Workers 100,000 requests/day · D1 5 GB · Workers KV 1 GB and 1,000 writes/day · Turnstile
unlimited. Photos are about 300 KB each, so KV holds roughly 3,000 featured photos;
waiting photos are deleted after 21 days if not featured.
