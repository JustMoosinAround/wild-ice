-- Ice Log storage. Codes, device keys and sender ids are stored only as SHA-256 hex.
CREATE TABLE friends (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('owner', 'friend')),
  revoked_at TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE invites (
  code_hash TEXT PRIMARY KEY,
  friend_id TEXT,
  role TEXT NOT NULL CHECK (role IN ('owner', 'friend')),
  name TEXT,
  created_at TEXT NOT NULL,
  used_at TEXT
);
CREATE TABLE devices (
  key_hash TEXT PRIMARY KEY,
  friend_id TEXT NOT NULL REFERENCES friends(id),
  created_at TEXT NOT NULL
);
CREATE TABLE reports (
  id TEXT PRIMARY KEY,
  idem_key TEXT UNIQUE NOT NULL,
  friend_id TEXT NOT NULL,
  lake_id TEXT NOT NULL,
  day TEXT NOT NULL,
  created_at TEXT NOT NULL,
  rating TEXT NOT NULL,
  grade TEXT,
  note TEXT NOT NULL DEFAULT '',
  lat REAL,
  lon REAL,
  gps_source TEXT CHECK (gps_source IN ('photo', 'device')),
  photo_id TEXT
);
CREATE TABLE photos (
  id TEXT PRIMARY KEY,
  public_id TEXT UNIQUE NOT NULL,
  lake_id TEXT NOT NULL,
  friend_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('pending', 'featured', 'rejected')),
  decided_at TEXT
);
CREATE TABLE comments (
  id TEXT PRIMARY KEY,
  lake_id TEXT NOT NULL,
  name TEXT NOT NULL,
  text TEXT NOT NULL,
  friend_id TEXT,
  sender_hash TEXT NOT NULL,
  created_at TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('pending', 'published', 'rejected'))
);
CREATE TABLE prefs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  lake_id TEXT NOT NULL,
  action TEXT NOT NULL CHECK (action IN ('pin', 'unpin', 'hide', 'unhide')),
  created_at TEXT NOT NULL
);
CREATE INDEX reports_day ON reports(day);
CREATE INDEX comments_lake ON comments(lake_id, status);
CREATE INDEX comments_sender ON comments(sender_hash, created_at);
CREATE INDEX photos_lake ON photos(lake_id, status);
