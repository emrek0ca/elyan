import { containsProtectedElyanDisclosure } from "../../lib/elyan-public-identity.js";

type RouteTransparencyDecision = {
  route?: string | null;
  userFacingMessage?: string | null;
  taskRoute?: {
    operationalRoute?: string | null;
    needsPrivateDesktopData?: boolean | null;
  } | null;
};

const DEFAULT_SERVER_MESSAGE = "Bu istek sohbet olarak işlenecek.";
const DEFAULT_DESKTOP_MESSAGE = "Bu görev masaüstünde çalışacak.";

function compactPublicMessage(
  value: string | null | undefined,
  maxLength = 240,
): string | undefined {
  const normalized = String(value ?? "")
    .replace(/\s+/g, " ")
    .trim();
  if (!normalized || containsProtectedElyanDisclosure(normalized)) {
    return undefined;
  }
  if (normalized.length <= maxLength) {
    return normalized;
  }
  return `${normalized.slice(0, maxLength - 1).trimEnd()}…`;
}

/**
 * Converts backend route truth into one safe, user-facing sentence.
 * Internal route reasons are intentionally excluded from this boundary.
 */
export function buildRouteTransparencyReason(
  decision: RouteTransparencyDecision | null | undefined,
): string | undefined {
  if (!decision) {
    return undefined;
  }

  const route = decision.taskRoute?.operationalRoute ?? decision.route;
  const userFacingMessage = compactPublicMessage(decision.userFacingMessage);

  if (decision.route === "pairing_required") {
    return userFacingMessage && userFacingMessage !== DEFAULT_DESKTOP_MESSAGE
      ? userFacingMessage
      : "Elyan masaüstü bağlantısı istedi çünkü görev yerel bilgisayar erişimi gerektiriyor.";
  }

  if (route === "desktop_runtime") {
    if (userFacingMessage && userFacingMessage !== DEFAULT_DESKTOP_MESSAGE) {
      return userFacingMessage;
    }
    return decision.taskRoute?.needsPrivateDesktopData
      ? "Elyan bunu masaüstünde çalıştırdı çünkü görev özel yerel veri veya bilgisayar erişimi gerektiriyor."
      : "Elyan bunu masaüstünde çalıştırdı çünkü masaüstü çalışma modu seçildi.";
  }

  if (route === "server_brain") {
    if (userFacingMessage && userFacingMessage !== DEFAULT_SERVER_MESSAGE) {
      return userFacingMessage;
    }
    return "Elyan bunu sohbet olarak işledi çünkü istek özel yerel veri veya bilgisayar erişimi gerektirmiyor.";
  }

  return userFacingMessage;
}
