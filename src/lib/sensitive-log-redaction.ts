export const VISION_LOG_REDACTION_PATHS = [
  "req.body.inputRefs",
  "req.body.ephemeralVision",
  "req.body.metadata.ephemeralVision",
  "req.body.metadata.attachments[*].base64Thumbnail",
  "req.body.metadata.clientAttachments[*].base64Thumbnail",
  "req.body.attachmentContext.visionImages[*].base64",
] as const;
