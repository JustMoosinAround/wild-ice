import { test } from "node:test";
import assert from "node:assert/strict";
import { parseActivityLink, sharedText } from "../../site/activitylink.js";

test("Strava and Garmin activity links give their GPX download", () => {
  const s = parseActivityLink("Check out my activity on Strava! https://www.strava.com/activities/12345678901");
  assert.equal(s.service, "Strava");
  assert.equal(s.gpxUrl, "https://www.strava.com/activities/12345678901/export_gpx");
  const g = parseActivityLink("https://connect.garmin.com/modern/activity/18765432100?share_unique_id=7");
  assert.equal(g.service, "Garmin Connect");
  assert.equal(g.id, "18765432100");
  assert.deepEqual(parseActivityLink("Morning Skate https://strava.app.link/AbCdEf123"), { short: "https://strava.app.link/AbCdEf123" });
  assert.equal(parseActivityLink("no link here"), null);
});

test("an Android share lands in the address", () => {
  assert.equal(sharedText("?share_title=Skate&share_url=https%3A%2F%2Fstrava.app.link%2Fx"), "https://strava.app.link/x Skate");
  assert.equal(sharedText(""), "");
});
