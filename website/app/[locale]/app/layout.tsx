export default function AppLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="fixed inset-0 bg-[var(--background)] overflow-hidden flex flex-col">
      {children}
    </div>
  );
}
