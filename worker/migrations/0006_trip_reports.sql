-- Public trip reports: the story a skater writes for everyone (notes stay private),
-- and kudos (one per member per report).
ALTER TABLE reports ADD COLUMN story TEXT;
CREATE TABLE kudos (
  report_id TEXT NOT NULL,
  friend_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (report_id, friend_id)
);
