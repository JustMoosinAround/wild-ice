-- Places people skate that aren't catalog lakes (marshes, rivers, sloughs, ponds), added
-- from a member's uploaded track. No satellite or ice model: their state is members' reports.
CREATE TABLE spots (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('marsh', 'river', 'slough', 'pond', 'other')),
  lat REAL NOT NULL,
  lon REAL NOT NULL,
  min_lon REAL NOT NULL, min_lat REAL NOT NULL, max_lon REAL NOT NULL, max_lat REAL NOT NULL,
  friend_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  hidden INTEGER NOT NULL DEFAULT 0
);
