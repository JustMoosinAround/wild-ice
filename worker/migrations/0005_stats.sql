-- Anonymous usage counts for the owner: installed copies of the app (a random id the
-- app makes for itself, no account, no IP) and daily tallies such as "Get the app" taps.
CREATE TABLE installs (
  id TEXT PRIMARY KEY,
  platform TEXT NOT NULL,
  first_seen TEXT NOT NULL,
  last_seen TEXT NOT NULL
);
CREATE TABLE tallies (
  day TEXT NOT NULL,
  name TEXT NOT NULL,
  n INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (day, name)
);
