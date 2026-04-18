import { Outlet } from "react-router-dom";

import { CommandPalette } from "@/shell/CommandPalette";
import { SidebarRail } from "@/shell/SidebarRail";
import { TitleBar } from "@/shell/TitleBar";

export function AppShell() {
  return (
    <div className="eylan-shell">
      <div className="eylan-window flex flex-col overflow-hidden">
        <TitleBar />
        <div className="flex min-h-0 flex-1">
          <SidebarRail />
          <main className="min-w-0 flex-1 overflow-auto bg-transparent px-4 py-4 lg:px-5 lg:py-5">
            <div className="mx-auto max-w-[1320px]">
              <Outlet />
            </div>
          </main>
        </div>
      </div>
      <CommandPalette />
    </div>
  );
}
