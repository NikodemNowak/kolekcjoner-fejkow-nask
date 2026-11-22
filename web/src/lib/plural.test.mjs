import assert from "node:assert/strict";
import { test } from "node:test";
import { NOUNS, plural, pluralWord } from "./plural.ts";

test("reports: 1 zgłoszenie, 2-4 zgłoszenia, 5+ zgłoszeń", () => {
  const expected = {
    0: "zgłoszeń", 1: "zgłoszenie", 2: "zgłoszenia", 3: "zgłoszenia", 4: "zgłoszenia", 5: "zgłoszeń",
    11: "zgłoszeń", 12: "zgłoszeń", 13: "zgłoszeń", 14: "zgłoszeń", 15: "zgłoszeń", 21: "zgłoszeń",
    22: "zgłoszenia", 24: "zgłoszenia", 25: "zgłoszeń", 100: "zgłoszeń", 102: "zgłoszenia", 112: "zgłoszeń",
  };
  for (const [n, word] of Object.entries(expected)) assert.equal(pluralWord(Number(n), "report"), word, n);
});

test("count with noun", () => {
  assert.equal(plural(2, "report"), "2 zgłoszenia");
  assert.equal(plural(1, "pair"), "1 para");
  assert.equal(plural(3, "pair"), "3 pary");
  assert.equal(plural(15, "pair"), "15 par");
  assert.equal(plural(4, "campaign"), "4 kampanie");
  assert.equal(plural(4, "operator"), "4 sprawcy");
  assert.equal(plural(5, "operator"), "5 sprawców");
  assert.equal(plural(21, "file"), "21 plików");
  assert.equal(plural(2, "domain"), "2 domeny");
  assert.equal(plural(4, "person"), "4 osoby");
  assert.equal(plural(7, "person"), "7 osób");
  assert.equal(plural(1, ["ślad", "ślady", "śladów"]), "1 ślad");
});

test("every noun has three distinct-enough forms", () => {
  for (const [key, forms] of Object.entries(NOUNS)) {
    assert.equal(forms.length, 3, key);
    for (const form of forms) assert.ok(form.length > 0, key);
  }
});
