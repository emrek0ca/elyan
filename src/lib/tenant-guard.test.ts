import assert from "node:assert/strict";
import test from "node:test";
import {
  filterRowsToTenant,
  getTenantMismatchTotal,
  resetTenantMismatchTotal,
} from "./tenant-guard.js";

test("tenant guard: eşleşen satırlar aynen geçer", () => {
  resetTenantMismatchTotal();
  const rows = [
    { id: "1", tenantUserId: "user-a", content: "x" },
    { id: "2", tenantUserId: "user-a", content: "y" },
  ];
  const safe = filterRowsToTenant({ rows, expectedUserId: "user-a", source: "test" });
  assert.equal(safe.length, 2);
  assert.equal(getTenantMismatchTotal(), 0);
});

test("tenant guard: başka kullanıcının satırı düşürülür ve loglanır", () => {
  resetTenantMismatchTotal();
  const logged: Array<Record<string, unknown>> = [];
  const rows = [
    { id: "1", tenantUserId: "user-a", content: "benim" },
    { id: "2", tenantUserId: "user-B-SALDIRGAN", content: "sızıntı" },
    { id: "3", tenantUserId: "user-a", content: "benim-2" },
  ];
  const safe = filterRowsToTenant({
    rows,
    expectedUserId: "user-a",
    source: "memory.search.test",
    logger: { error: (obj) => logged.push(obj) },
  });
  assert.equal(safe.length, 2);
  assert.ok(safe.every((row) => row.tenantUserId === "user-a"));
  assert.equal(getTenantMismatchTotal(), 1);
  assert.equal(logged.length, 1);
  assert.equal(logged[0].severity, "tenant_isolation_violation");
  assert.equal(logged[0].droppedRows, 1);
});

test("tenant guard: tenant alanı olmayan satır güvenli sayılır (opt-in)", () => {
  resetTenantMismatchTotal();
  const rows = [{ id: "1", content: "tenant kolonu select edilmemiş" }];
  const safe = filterRowsToTenant({ rows, expectedUserId: "user-a", source: "test" });
  assert.equal(safe.length, 1);
  assert.equal(getTenantMismatchTotal(), 0);
});

test("tenant guard: boş expectedUserId hiçbir satırı düşürmez", () => {
  resetTenantMismatchTotal();
  const rows = [{ id: "1", tenantUserId: "user-x" }];
  const safe = filterRowsToTenant({ rows, expectedUserId: "", source: "test" });
  assert.equal(safe.length, 1);
});

test("tenant guard: uuid tip farkları string karşılaştırmayla tolere edilir", () => {
  resetTenantMismatchTotal();
  const rows = [{ id: "1", tenantUserId: "0AF0-1", content: "x" }];
  const safe = filterRowsToTenant({ rows, expectedUserId: "0AF0-1", source: "test" });
  assert.equal(safe.length, 1);
  assert.equal(getTenantMismatchTotal(), 0);
});
