-- Open sign-up: who joined from where (hashed), to rate-limit new accounts per connection.
ALTER TABLE friends ADD COLUMN join_hash TEXT;
CREATE INDEX IF NOT EXISTS friends_join ON friends (join_hash, created_at);
