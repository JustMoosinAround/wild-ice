-- Account page: profile photos, and which phones are signed in.
ALTER TABLE friends ADD COLUMN avatar_id TEXT;
ALTER TABLE devices ADD COLUMN label TEXT;
ALTER TABLE devices ADD COLUMN last_seen TEXT;
