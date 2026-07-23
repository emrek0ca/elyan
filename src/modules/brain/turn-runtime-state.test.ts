import assert from "node:assert/strict";
import test from "node:test";
import { buildTurnRuntimeStatePromptBlock } from "./turn-runtime-state.js";

test("binds short image color follow-up to the latest session artifact", () => {
  const block = buildTurnRuntimeStatePromptBlock({
    prompt: "Başka renkte çiz",
    conversation: [
      { role: "user", content: "Bana bi kedi resmi çizer misin" },
      { role: "assistant", content: "İşte beyaz bir kedi resmi:" },
    ],
    requestMetadata: {
      sessionArtifacts: [
        {
          id: "artifact_img_1",
          artifactType: "image",
          name: "White cat",
          revisedPrompt: "A white cat sitting near a sunny window",
        },
      ],
    },
    route: "shared_brain",
    workload: "image_generation",
    taskId: "task_1",
  });

  assert.match(block ?? "", /operation=image_variation/);
  assert.match(block ?? "", /target=last_artifact/);
  assert.match(block ?? "", /must_use_target=yes/);
  assert.match(block ?? "", /latest_artifact: id=artifact_img_1/);
  assert.match(block ?? "", /Preserve|preserve: main_subject/);
});

test("keeps a normal greeting as a new topic", () => {
  const block = buildTurnRuntimeStatePromptBlock({
    prompt: "Selam nasılsın?",
    conversation: [{ role: "assistant", content: "Buradayım." }],
    requestMetadata: {
      sessionArtifacts: [
        {
          id: "artifact_img_1",
          artifactType: "image",
          name: "White cat",
        },
      ],
    },
  });

  assert.match(block ?? "", /mode=new_topic/);
  assert.match(block ?? "", /target=none/);
  assert.match(block ?? "", /must_use_target=no/);
});

test("carries recent conversation and latest artifact into the prompt block", () => {
  const block = buildTurnRuntimeStatePromptBlock({
    prompt: "Daha sinematik yap",
    conversation: [
      { role: "user", content: "Bir şehir görseli üret" },
      { role: "assistant", content: "Şehir görselini oluşturdum." },
    ],
    requestMetadata: {
      sessionArtifacts: [
        {
          id: "artifact_city",
          contentFamily: "image",
          name: "City",
          prompt: "A modern city skyline at sunset",
        },
      ],
    },
  });

  assert.match(block ?? "", /last_user: Bir şehir görseli üret/);
  assert.match(block ?? "", /last_assistant: Şehir görselini oluşturdum/);
  assert.match(block ?? "", /operation=style_transfer/);
  assert.match(block ?? "", /prompt=A modern city skyline at sunset/);
});
