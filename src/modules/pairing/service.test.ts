import assert from "node:assert/strict";
import test from "node:test";
import { devices, pairSessions } from "../../db/schema.js";
import { createPairSession } from "./service.js";

function createSelectBuilder(result: unknown) {
  return {
    from() {
      return this;
    },
    where() {
      return this;
    },
    limit: async () => result,
  };
}

test("createPairSession reuses a stable desktop row and expires old pending sessions", async () => {
  const existingDevice = {
    id: "desktop-1",
    userId: "user-1",
    externalDeviceId: "desktop-ext-1",
    label: "Old label",
    platform: "macos",
    runtimeVersion: "0.9.0",
  };
  const updateCalls: Array<{ table: unknown; values: Record<string, unknown> }> = [];
  const insertCalls: Array<{ table: unknown; values: Record<string, unknown> }> = [];
  const selectResults = [
    [
      {
        planCode: "pro",
        status: "active",
        trialEndsAt: null,
      },
    ],
    [
      {
        count: 0,
      },
    ],
    [existingDevice],
  ];

  const app = {
    config: {
      PAIRING_TTL_MINUTES: 10,
    },
    db: {
      select() {
        return createSelectBuilder(selectResults.shift() ?? []);
      },
      update(table: unknown) {
        return {
          set(values: Record<string, unknown>) {
            updateCalls.push({ table, values });
            return {
              where() {
                return {
                  returning: async () =>
                    table === devices
                      ? [
                          {
                            ...existingDevice,
                            userId: "user-1",
                            label: String(values.label ?? existingDevice.label),
                            platform: String(values.platform ?? existingDevice.platform),
                            runtimeVersion: String(values.runtimeVersion ?? existingDevice.runtimeVersion),
                          },
                        ]
                      : [],
                };
              },
            };
          },
        };
      },
      insert(table: unknown) {
        return {
          values(values: Record<string, unknown>) {
            insertCalls.push({ table, values });
            return {
              returning: async () => [
                {
                  id: "session-1",
                  desktopDeviceId: "desktop-1",
                  expiresAt: new Date("2030-05-22T15:30:00.000Z"),
                  status: "pending",
                },
              ],
            };
          },
        };
      },
    },
  };

  const result = await createPairSession(app as never, {
    userId: "user-1",
    deviceLabel: "Elyan",
    platform: "macos",
    runtimeVersion: "1.0.0",
    externalDeviceId: "desktop-ext-1",
  });

  const pairInsert = insertCalls.find((entry) => entry.table === pairSessions);
  assert.ok(pairInsert);
  assert.equal(pairInsert?.values.desktopDeviceId, "desktop-1");
  assert.equal(insertCalls.filter((entry) => entry.table === devices).length, 0);
  assert.equal(updateCalls.filter((entry) => entry.table === pairSessions).length, 2);
  assert.equal(updateCalls.filter((entry) => entry.table === devices).length, 1);
  assert.equal(result.desktopDevice.id, "desktop-1");
  assert.equal(result.qrText.startsWith("elyan://pair?sessionId=session-1&pairingCode="), true);
  assert.equal(result.manualEntryCode.startsWith("session-1|"), true);
  assert.equal(result.qrPayload.manualEntryCode, result.manualEntryCode);
  assert.equal(result.qrPayload.schemaVersion, 1);
});
