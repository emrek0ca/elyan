CREATE UNIQUE INDEX "usage_records_task_metric_uidx" ON "usage_records" USING btree ("task_id","metric");
INSERT INTO "usage_records" ("user_id","task_id","metric","quantity","created_at") SELECT "user_id","id",'trial_task',1,"created_at" FROM "tasks" ON CONFLICT ("task_id","metric") DO NOTHING;
