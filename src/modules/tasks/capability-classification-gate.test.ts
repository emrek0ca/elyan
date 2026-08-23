import assert from "node:assert/strict";
import test from "node:test";
import { DESKTOP_CAPABILITY_MANIFEST } from "./desktop-capability-manifest.js";
import { localActionCapabilityNames } from "./desktop-capability-embedding-match.js";

// ---------------------------------------------------------------------------
// TÜRETİLMİŞ KÜME DENETİM KAPISI — sunucu tarafı.
//
// Masaüstü tarafındaki eşi: tests/test_capability_classification_gate.py.
// İkisi AYNI manifesti farklı uçlardan denetler; sürükleme tam olarak bu iki
// repo arasında sessizce oluyordu.
//
// Kapının varlık sebebi ölçülmüş bir arıza: yerel-eylem kümesi
// `privacyClass` ile türetiliyordu, sınıfsız yetenekler `local_runtime`
// torbasına düşüyordu ve torbada `browser_session.click`, `git_commit`,
// `shell_session_run`, `desktop_os.volume` gibi GERÇEK makine eylemleri
// vardı. Kapı yapısal olarak onlara "yerel yürüt" diyemiyordu.
// ---------------------------------------------------------------------------

const BAG_PRIVACY_CLASS = "local_runtime";

const PRIVACY_CLASSES = new Set([
  BAG_PRIVACY_CLASS,
  "local_private_action",
  "permission_gated",
  "local_private_write",
  "local_private_read",
  "local_private_screen",
  "local_private_mixed",
  "local_session_control",
  "local_safe_compute",
  "local_or_server_context",
  "external_model_optional",
  "public_web",
]);

test("every manifest entry carries a privacy class from the closed vocabulary", () => {
  const unknown = DESKTOP_CAPABILITY_MANIFEST.filter(
    (entry) => !PRIVACY_CLASSES.has(entry.privacyClass),
  ).map((entry) => `${entry.name}=${entry.privacyClass}`);
  assert.deepEqual(unknown, [], `sözlükte olmayan gizlilik sınıfı: ${unknown}`);
});

test("no side-effecting capability is left in the bag class", () => {
  // Torba bir karar değil, sınıflandırma kaçağıdır. Yan etkili bir iş oraya
  // düşerse yönlendirme onu bir daha yerel eylem olarak göremez.
  const leaked = DESKTOP_CAPABILITY_MANIFEST.filter(
    (entry) => entry.sideEffect && entry.privacyClass === BAG_PRIVACY_CLASS,
  ).map((entry) => entry.name);
  assert.deepEqual(leaked, [], `yan etkili yetenek torbada: ${leaked}`);
});

test("path-mutating capabilities are declared, not guessed from the class name", () => {
  // ESKİ HÂL: iş emri yazma köklerini `privacyClass.includes("_write")` ile
  // seçiyordu. `make_directory`, `file_move`, `move_to_trash`
  // `local_private_action` sınıfında oldukları için — diske YAZDIKLARI hâlde —
  // OKUMA kökü sayılıyorlardı. Sınıf adının içinde alt dize aramak bir kapı
  // değildir; beyan edilen alan kapıdır.
  const mutating = DESKTOP_CAPABILITY_MANIFEST.filter((entry) => entry.mutatesPath)
    .map((entry) => entry.name)
    .sort();
  for (const name of [
    "make_directory",
    "file_move",
    "move_to_trash",
    "file_write",
    "file_patch",
    "document_write",
  ]) {
    assert.ok(mutating.includes(name), `${name} yol değiştiren sayılmadı`);
  }
  // Salt-okunur/hesap işleri asla yazma kökü açmamalı.
  for (const name of ["file_read", "web_research", "get_weather", "sys_info"]) {
    assert.equal(mutating.includes(name), false, `${name} yanlışlıkla yazıcı sayıldı`);
  }
});

test("the local action set stays deliberate after classification", () => {
  const names = localActionCapabilityNames();
  // Sınıflandırma öncesi 19'du; torbadan çıkarılan 8 gerçek makine eylemiyle
  // 27 oldu (browser_session.goto/click/type/download, desktop_os.volume,
  // git_commit, git_branch, shell_session_run).
  //
  // ÜST SINIRIN KORUDUĞU ŞEY: bu küme "her masaüstü yeteneği" olmamalı —
  // öyle olursa yönlendirme kanıtı anlamını yitirir. 27/84 hâlâ üçte bir;
  // sınır ölçüyle birlikte yükseltildi, ölçüsüz değil.
  assert.ok(names.length >= 8 && names.length <= 32, `beklenmedik boyut: ${names.length}`);
  for (const name of [
    "browser_session.click",
    "git_commit",
    "shell_session_run",
    "desktop_os.volume",
  ]) {
    assert.ok(names.includes(name), `${name} yerel eylem sayılmadı`);
  }
  // Sunucunun da yapabildiği işler dışarıda kalmalı.
  for (const name of ["get_weather", "web_research", "document_write", "chart_generate"]) {
    assert.equal(names.includes(name), false, `${name} yanlışlıkla yerel eylem sayıldı`);
  }
  // `desktop_operator.cancel` yan etkili AMA kullanıcı hedefi değil: kontrol
  // sözcüğü ("iptal") yönlendirme kanıtı olursa sohbet masaüstüne kaçar.
  assert.equal(names.includes("desktop_operator.cancel"), false);
});
