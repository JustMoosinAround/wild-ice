-- Explore app: saved lakes per friend; reports made from an uploaded track.
CREATE TABLE saved (
  friend_id TEXT NOT NULL,
  lake_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (friend_id, lake_id)
);
-- Minutes on the lake from an uploaded GPX/FIT track (the track itself is never stored).
ALTER TABLE reports ADD COLUMN track_minutes INTEGER;
