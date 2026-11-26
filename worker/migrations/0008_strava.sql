-- Connect Strava: one connection per member (tokens to read their own activities), and
-- which reports came from Strava (their track details are never shown to anyone else).
CREATE TABLE strava (
  friend_id TEXT PRIMARY KEY,
  athlete_id TEXT NOT NULL,
  athlete_name TEXT,
  access_token TEXT NOT NULL,
  refresh_token TEXT NOT NULL,
  expires_at INTEGER NOT NULL,
  created_at TEXT NOT NULL
);
ALTER TABLE reports ADD COLUMN via TEXT;
