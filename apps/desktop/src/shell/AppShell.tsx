import { Outlet } from "react-router-dom";

import { CommandPalette } from "@/shell/CommandPalette";
import { SidebarRail } from "@/shell/SidebarRail";
import { TitleBar } from "@/shell/TitleBar";
import { TopCommandBar } from "@/shell/TopCommandBar";

export function AppShell() {
  return (
    <div className="eylan-shell">
      <div className="eylan-window flex flex-col overflow-hidden">
        <TitleBar />
        <div className="flex min-h-0 flex-1">
          <SidebarRail />
          <main className="min-w-0 flex-1 overflow-auto bg-transparent px-7 py-7">
            <div className="mx-auto max-w-[1180px]">
              <TopCommandBar />
              <Outlet />
            </div>
          </main>
        </div>
      </div>
      <CommandPalette />
    </div>
  );
}
