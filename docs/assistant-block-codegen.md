# Assistant block schema and Dart code generation

`src/contracts/assistant-block-schemas.ts` is the only handwritten source for
assistant block types, envelopes, source-widget payloads, and widget states.
The generated JSON Schema and Dart files must never be edited directly.

The canonical block envelope is additive to the existing `elyan_blocks.v2`
transport. Its `version` is the integer `1`; this does not rename or replace the
transport contract.

```json
{
  "type": "mail_list",
  "version": 1,
  "blockId": "gmail:mail_list:inbox",
  "source": "gmail",
  "visibility": "user_visible",
  "renderHints": {},
  "data": {
    "state": "empty",
    "items": []
  }
}
```

Legacy top-level payload fields remain accepted and may coexist with the new
envelope while stored histories and older clients migrate. New readers use
`data`; old readers continue to use their existing flat fields.

Generate the committed backend artifact:

```bash
npm run blocks:schema
```

The output is `contracts/generated/assistant-blocks.schema.json`. Its
`x-elyan-schema-digest` is SHA-256 over the canonical, pretty-printed schema
before that digest property is inserted. Type order follows the exported Zod
manifest and is stable.

From the mobile repository, synchronize this generated artifact and regenerate
all Dart models:

```bash
npm --prefix tool/assistant_blocks run sync
```

Generated Dart files live under
`lib/features/tasks/domain/blocks/models/generated/`. Every file carries the
same schema digest and a `DO NOT MODIFY BY HAND` header. A model change starts
in the Zod source, then regenerates the JSON Schema and Dart outputs together.

`connector_result` remains in the contract only for old messages. New connector
results use `mail_list`, `mail_detail`, `calendar_agenda`, `drive_files`,
`notion_page`, `github_activity`, or `slack_messages`.

