/**
 * CAPABILITY RİSK SÖZLÜĞÜ — tek tanım, iki tüketici.
 *
 * Bu desenler hem yetki üretiminde (`task-execution-contract`) hem şablon
 * sentezinde (`template-synthesis`) kullanılır. İkiye kopyalanırsa biri
 * güncellenip diğeri unutulur ve güvenlik kararı sessizce ayrışır; güvenlik
 * kuralının tek bir yeri olmalı.
 *
 * Desenler DENY yönünde çalışır: bir capability adının bu listelerde OLMAMASI
 * onu güvenli yapmaz, olması ise yetkiyi geri çeker. Ad hiçbir zaman güvenlik
 * kanıtı değildir — yalnız yetki kısıtlama gerekçesidir.
 */

/**
 * Ayrı onay gerektiren eylem sınıfları. Adın kendisi eylemi ele veriyorsa
 * argümana bakmaya gerek yoktur.
 */
export const SEPARATE_APPROVAL_CAPABILITY_PATTERN =
  /(?:credential|password|secret|payment|billing|purchase|delete|trash|erase|wipe|overwrite|upload|share|send|message|email|system_settings|settings_write)/iu;

/**
 * GENERIC YÜRÜTÜCÜLER — etkisi adında değil ARGÜMANINDA yaşayan araçlar.
 *
 * `desktop_operator.run` bir pencere odaklayabildiği gibi bir dosyayı da
 * silebilir; `mcp_call_tool` çağırdığı alt araca göre her şeyi yapabilir. Bu
 * yüzden bunlara önceden yetki verilmez ve öğrenilmiş bir şablona da
 * girmezler: şablon, argümanı bilinmeyen bir eylemi "güvenli" ilan edemez.
 */
export const GENERIC_EXECUTOR_CAPABILITY_PATTERN =
  /(?:^|[._-])(?:desktop_operator|desktop_agent|browser_control|browser_agent|browser_use|computer_use|computer_control|mcp_call_tool|mcp_call|call_tool|run_skill|run_command|run_script|shell|bash|zsh|sh_exec|terminal|command_line|exec|execute_action|execute_command|applescript|osascript|python_exec|eval)(?:$|[._-])/iu;

/**
 * Argüman gövdesinde YÜKSELTİLMİŞ risk.
 *
 * Ayrı onay gerektiren eylemler capability adına yazılmayabilir; kritik olan
 * argümanın kendisidir (`{"command": "rm -rf ..."}`, `{"action": "purchase"}`).
 */
export const ELEVATED_RISK_ARGUMENT_PATTERN =
  /(?:\brm\s+-[rf]|\bsudo\b|\bchmod\b|\bchown\b|\bkillall\b|\bdefaults\s+write\b|\bcurl\b|\bwget\b|\bpip\s+install\b|\bnpm\s+i(?:nstall)?\b|\bbrew\s+install\b|password|passphrase|secret|api[_-]?key|token|credential|payment|purchase|checkout|transfer|delete|erase|wipe|overwrite|uninstall)/iu;

export function isGenericExecutorCapability(capability: string): boolean {
  return GENERIC_EXECUTOR_CAPABILITY_PATTERN.test(String(capability ?? ""));
}

export function needsSeparateApproval(capability: string): boolean {
  return SEPARATE_APPROVAL_CAPABILITY_PATTERN.test(String(capability ?? ""));
}
