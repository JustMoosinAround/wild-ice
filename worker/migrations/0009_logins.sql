-- Accounts log in with a username (or email) and password. Only a salted PBKDF2 hash
-- of the password is kept. Older accounts can add a login from their Account page.
ALTER TABLE friends ADD COLUMN username TEXT;
ALTER TABLE friends ADD COLUMN email TEXT;
ALTER TABLE friends ADD COLUMN pass_hash TEXT;
ALTER TABLE friends ADD COLUMN pass_salt TEXT;
CREATE UNIQUE INDEX friends_username ON friends (lower(username)) WHERE username IS NOT NULL;
CREATE UNIQUE INDEX friends_email ON friends (lower(email)) WHERE email IS NOT NULL;
-- Password reset links (only a hash of the token), and failed logins for rate limiting.
CREATE TABLE password_resets (
  token_hash TEXT PRIMARY KEY,
  friend_id TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  used_at TEXT
);
CREATE TABLE login_fails (
  key_hash TEXT NOT NULL,
  at TEXT NOT NULL
);
CREATE INDEX login_fails_key ON login_fails (key_hash, at);
