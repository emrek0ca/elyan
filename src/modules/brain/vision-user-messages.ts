import type { VisionTaskDecision } from "./vision-task-policy.js";

export type VisionMessageLocale = "tr" | "en" | "es" | "fr" | "de" | "it" | "pt" | "ru" | "ar";

export function detectVisionMessageLocale(prompt: string): VisionMessageLocale {
  const text = String(prompt ?? "").toLocaleLowerCase("tr-TR");
  if (/\p{Script=Arabic}/u.test(text)) return "ar";
  if (/\p{Script=Cyrillic}/u.test(text)) return "ru";
  if (/[çğıöşü]|\b(?:bu|görsel|gorsel|resim|ekran|oku|açıkla|acikla|karşılaştır|karsilastir)\b/u.test(text)) return "tr";
  if (/[¿¡ñ]|\b(?:imagen|pantalla|leer|compara|explica)\b/u.test(text)) return "es";
  if (/\b(?:cette|écran|ecran|lire|comparez|expliquez)\b/u.test(text)) return "fr";
  if (/[äöüß]|\b(?:dieses|diese|bild|foto|bildschirm|lesen|vergleiche|erkläre|erklaere)\b/u.test(text)) return "de";
  if (/\b(?:questa|questo|immagine|foto|schermo|leggi|confronta|spiega)\b/u.test(text)) return "it";
  if (/[ãõ]|\b(?:imagem|tela|leia|compare|explique)\b/u.test(text)) return "pt";
  return "en";
}

const MESSAGES: Record<VisionMessageLocale, {
  missing: string;
  busy: string;
  conflict: string;
  privacy: string;
  comparison: string;
  fineDetail: Record<"screen" | "amounts" | "general", string>;
}> = {
  tr: {
    missing: "Görsel doğrulanamadı. Daha net veya ilgili bölgeye yakınlaştırılmış hâlini yeniden gönderir misin?",
    busy: "Görsel işleme şu anda yoğun. Birkaç saniye sonra aynı görseli yeniden gönderir misin?",
    conflict: "Görseldeki kritik değer iki okumada aynı çıkmadı. İlgili kod veya tutarın daha net bir yakın çekimini gönderir misin? Tahmin etmek istemiyorum.",
    privacy: "Bu görsel hassas kimlik veya erişim bilgisi içeriyor olabilir. Güvenlik için dış görsel işlemeye göndermedim; hassas alanları kapatıp yeniden gönderir misin?",
    comparison: "Görsellerden biri güvenilir biçimde okunamadı. Sağlıklı karşılaştırabilmem için eksik veya bulanık olan görseli yeniden gönderir misin?",
    fineDetail: {
      screen: "Hata mesajının bulunduğu bölümü daha yakından ve net şekilde gönderir misin? Bu görüntüde kesin metin çıkarmak güvenilir değil.",
      amounts: "Tutarların bulunduğu bölümü daha yakından ve net şekilde gönderir misin? Bu görüntüde rakamları güvenilir biçimde okuyamıyorum.",
      general: "Okumamı istediğin bölümü daha yakından ve net şekilde gönderir misin? Bu görüntüde kesin metin çıkarmak güvenilir değil.",
    },
  },
  en: {
    missing: "I couldn't verify the image. Please send a clearer version or a closer crop of the relevant area.",
    busy: "Image processing is busy right now. Please send the same image again in a few seconds.",
    conflict: "The critical value was read differently in two passes. Please send a clearer close-up of the code or amount so I don't guess.",
    privacy: "This image may contain sensitive identity or access information. I did not send it for external image processing; please hide the sensitive areas and send it again.",
    comparison: "One of the images could not be read reliably. Please resend the missing or blurry image so I can compare them accurately.",
    fineDetail: { screen: "Please send a clearer close-up of the error message. The exact text isn't reliable in this image.", amounts: "Please send a clearer close-up of the amounts. The numbers aren't reliable in this image.", general: "Please send a clearer close-up of the section you want me to read. Exact text isn't reliable in this image." },
  },
  es: {
    missing: "No pude verificar la imagen. Envíame una versión más nítida o un recorte cercano de la zona relevante.",
    busy: "El procesamiento de imágenes está ocupado ahora. Vuelve a enviar la misma imagen en unos segundos.",
    conflict: "El valor crítico se leyó de forma distinta en dos pasadas. Envíame un acercamiento más nítido del código o importe para no adivinar.",
    privacy: "Esta imagen puede contener datos sensibles de identidad o acceso. No la envié para procesamiento externo; oculta esas zonas y vuelve a enviarla.",
    comparison: "No pude leer bien una de las imágenes. Vuelve a enviar la que falta o está borrosa para poder compararlas con precisión.",
    fineDetail: { screen: "Envíame un acercamiento más nítido del mensaje de error; el texto exacto no se distingue con fiabilidad.", amounts: "Envíame un acercamiento más nítido de los importes; los números no se distinguen con fiabilidad.", general: "Envíame un acercamiento más nítido de la parte que quieres que lea; el texto exacto no se distingue con fiabilidad." },
  },
  fr: {
    missing: "Je n’ai pas pu vérifier l’image. Envoie une version plus nette ou un gros plan de la zone concernée.",
    busy: "Le traitement des images est momentanément occupé. Renvoie la même image dans quelques secondes.",
    conflict: "La valeur critique a été lue différemment lors de deux analyses. Envoie un gros plan plus net du code ou du montant pour éviter toute supposition.",
    privacy: "Cette image peut contenir des données sensibles d’identité ou d’accès. Je ne l’ai pas envoyée au traitement externe ; masque ces zones et renvoie-la.",
    comparison: "L’une des images n’est pas suffisamment lisible. Renvoie l’image manquante ou floue pour que je puisse les comparer correctement.",
    fineDetail: { screen: "Envoie un gros plan plus net du message d’erreur ; le texte exact n’est pas assez lisible.", amounts: "Envoie un gros plan plus net des montants ; les chiffres ne sont pas assez lisibles.", general: "Envoie un gros plan plus net de la zone à lire ; le texte exact n’est pas assez lisible." },
  },
  de: {
    missing: "Ich konnte das Bild nicht zuverlässig prüfen. Sende bitte eine schärfere Version oder einen näheren Ausschnitt des relevanten Bereichs.",
    busy: "Die Bildverarbeitung ist gerade ausgelastet. Sende dasselbe Bild bitte in einigen Sekunden erneut.",
    conflict: "Der kritische Wert wurde in zwei Durchläufen unterschiedlich gelesen. Sende bitte eine schärfere Nahaufnahme des Codes oder Betrags, damit ich nicht raten muss.",
    privacy: "Dieses Bild kann sensible Identitäts- oder Zugangsdaten enthalten. Ich habe es nicht extern verarbeiten lassen; verdecke diese Bereiche und sende es erneut.",
    comparison: "Eines der Bilder ist nicht zuverlässig lesbar. Sende das fehlende oder unscharfe Bild erneut, damit ich beide korrekt vergleichen kann.",
    fineDetail: { screen: "Sende bitte eine schärfere Nahaufnahme der Fehlermeldung; der genaue Text ist hier nicht zuverlässig lesbar.", amounts: "Sende bitte eine schärfere Nahaufnahme der Beträge; die Zahlen sind hier nicht zuverlässig lesbar.", general: "Sende bitte eine schärfere Nahaufnahme des Bereichs, den ich lesen soll; der genaue Text ist hier nicht zuverlässig lesbar." },
  },
  it: {
    missing: "Non sono riuscito a verificare l’immagine. Invia una versione più nitida o un ritaglio ravvicinato dell’area interessata.",
    busy: "L’elaborazione delle immagini è momentaneamente occupata. Invia di nuovo la stessa immagine tra qualche secondo.",
    conflict: "Il valore critico è stato letto in modo diverso in due passaggi. Invia un primo piano più nitido del codice o dell’importo, così evito di fare ipotesi.",
    privacy: "L’immagine potrebbe contenere dati sensibili di identità o accesso. Non l’ho inviata all’elaborazione esterna; copri quelle aree e inviala di nuovo.",
    comparison: "Una delle immagini non è leggibile con affidabilità. Invia di nuovo quella mancante o sfocata così potrò confrontarle correttamente.",
    fineDetail: { screen: "Invia un primo piano più nitido del messaggio di errore; il testo esatto non è leggibile con affidabilità.", amounts: "Invia un primo piano più nitido degli importi; i numeri non sono leggibili con affidabilità.", general: "Invia un primo piano più nitido della parte da leggere; il testo esatto non è leggibile con affidabilità." },
  },
  pt: {
    missing: "Não consegui verificar a imagem. Envie uma versão mais nítida ou um recorte aproximado da área relevante.",
    busy: "O processamento de imagens está ocupado no momento. Envie a mesma imagem novamente em alguns segundos.",
    conflict: "O valor crítico foi lido de forma diferente em duas análises. Envie uma aproximação mais nítida do código ou valor para que eu não precise adivinhar.",
    privacy: "Esta imagem pode conter dados sensíveis de identidade ou acesso. Não a enviei para processamento externo; oculte essas áreas e envie novamente.",
    comparison: "Uma das imagens não está legível o suficiente. Reenvie a imagem ausente ou desfocada para que eu possa compará-las corretamente.",
    fineDetail: { screen: "Envie uma aproximação mais nítida da mensagem de erro; o texto exato não está legível com segurança.", amounts: "Envie uma aproximação mais nítida dos valores; os números não estão legíveis com segurança.", general: "Envie uma aproximação mais nítida da área que devo ler; o texto exato não está legível com segurança." },
  },
  ru: {
    missing: "Не удалось надёжно распознать изображение. Пришлите более чёткую версию или крупный фрагмент нужной области.",
    busy: "Обработка изображений сейчас занята. Пришлите то же изображение ещё раз через несколько секунд.",
    conflict: "Критическое значение было прочитано по-разному в двух проходах. Пришлите более чёткий крупный фрагмент кода или суммы, чтобы не приходилось угадывать.",
    privacy: "Изображение может содержать конфиденциальные идентификационные данные или данные доступа. Я не отправлял его на внешнюю обработку; скройте эти области и пришлите снова.",
    comparison: "Одно из изображений не удалось надёжно прочитать. Пришлите отсутствующее или размытое изображение ещё раз, чтобы я мог корректно их сравнить.",
    fineDetail: { screen: "Пришлите более чёткий крупный фрагмент сообщения об ошибке: точный текст сейчас читается ненадёжно.", amounts: "Пришлите более чёткий крупный фрагмент с суммами: цифры сейчас читаются ненадёжно.", general: "Пришлите более чёткий крупный фрагмент нужного текста: сейчас он читается ненадёжно." },
  },
  ar: {
    missing: "لم أتمكن من التحقق من الصورة بدقة. أرسل نسخة أوضح أو لقطة مقرّبة للجزء المطلوب.",
    busy: "معالجة الصور مشغولة الآن. أرسل الصورة نفسها مرة أخرى بعد بضع ثوانٍ.",
    conflict: "تمت قراءة القيمة المهمة بشكل مختلف في المحاولتين. أرسل لقطة أوضح ومقرّبة للرمز أو المبلغ حتى لا أخمّن.",
    privacy: "قد تحتوي الصورة على بيانات حساسة للهوية أو الوصول. لم أرسلها للمعالجة الخارجية؛ أخفِ هذه الأجزاء ثم أرسلها مرة أخرى.",
    comparison: "إحدى الصورتين غير واضحة بما يكفي. أعد إرسال الصورة المفقودة أو الضبابية كي أتمكن من المقارنة بدقة.",
    fineDetail: { screen: "أرسل لقطة أوضح ومقرّبة لرسالة الخطأ؛ النص الدقيق غير مقروء بشكل موثوق.", amounts: "أرسل لقطة أوضح ومقرّبة للمبالغ؛ الأرقام غير مقروءة بشكل موثوق.", general: "أرسل لقطة أوضح ومقرّبة للجزء الذي تريد قراءته؛ النص الدقيق غير مقروء بشكل موثوق." },
  },
};

export function buildVisionRecoveryMessage(input: {
  prompt: string;
  reason: "missing" | "busy" | "conflict" | "privacy" | "comparison" | "fine_detail";
  task: VisionTaskDecision;
}): string {
  const messages = MESSAGES[detectVisionMessageLocale(input.prompt)];
  if (input.reason === "missing") return messages.missing;
  if (input.reason === "busy") return messages.busy;
  if (input.reason === "conflict") return messages.conflict;
  if (input.reason === "privacy") return messages.privacy;
  if (input.reason === "comparison") return messages.comparison;
  const target = input.task.primary === "screen_debugging" || input.task.primary === "code_screenshot"
    ? "screen"
    : input.task.primary === "receipt_or_invoice"
      ? "amounts"
      : "general";
  return messages.fineDetail[target];
}
