'use client';

import React from 'react';
import { motion } from 'framer-motion';
import { Search, SlidersHorizontal } from 'lucide-react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';

export function Sidebar() {
  const pathname = usePathname();
  const isSearchActive = pathname === '/' || pathname.startsWith('/chat');
  const isManageActive = pathname.startsWith('/manage');

  return (
    <motion.aside
      initial={{ x: -280 }}
      animate={{ x: 0 }}
      className="sidebar"
    >
      <div className="sidebar__brand">
        <div className="sidebar__logo">
          E
        </div>
        <span className="sidebar__brand-text">
          Elyan
        </span>
      </div>

      <nav className="sidebar__nav" aria-label="Primary">
        <NavItem href="/" icon={<Search size={20} />} label="Search" active={isSearchActive} />
        <NavItem href="/manage" icon={<SlidersHorizontal size={20} />} label="Manage" active={isManageActive} />
      </nav>

      <div className="sidebar__footer">
        Local-first runtime. Optional search, MCP, channels, and hosted control-plane stay outside private local context.
      </div>
    </motion.aside>
  );
}

function NavItem({
  href,
  icon,
  label,
  active,
}: {
  href: string;
  icon: React.ReactNode;
  label: string;
  active?: boolean;
}) {
  return (
    <Link
      href={href}
      className={active ? 'sidebar__nav-item sidebar__nav-item--active' : 'sidebar__nav-item'}
      aria-current={active ? 'page' : undefined}
    >
      {icon}
      <span className="sidebar__nav-label">{label}</span>
    </Link>
  );
}
