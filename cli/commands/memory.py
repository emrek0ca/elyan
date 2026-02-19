"""
CLI: memory commands — Full implementation
"""
import asyncio
import json
import click


@click.group("memory")
def memory_group():
    """Bellek yönetimi."""
    pass


@memory_group.command("status")
@click.option("--user", default=None, type=int, help="Kullanıcı ID için kullanım detayı")
def memory_status(user):
    """Bellek durumunu göster."""
    try:
        from core.memory import MemoryManager
        mm = MemoryManager()
        if asyncio.iscoroutinefunction(mm.get_stats):
            stats = asyncio.run(mm.get_stats(user_id=user))
        else:
            stats = mm.get_stats(user_id=user)
        click.echo(f"Bellek Durumu")
        click.echo(f"  Toplam öğe:  {stats.get('total_items', 0)}")
        click.echo(f"  Boyut:       {stats.get('size_mb', 0):.1f} MB")
        click.echo(f"  Yol:         {stats.get('path', '~/.elyan/memory/')}")
        click.echo(f"  İndeks:      {'✓ Güncel' if stats.get('index_ok') else '⚠️  Güncellenmeli'}")
        if stats.get("user_storage"):
            us = stats["user_storage"]
            click.echo(f"  Kullanıcı:   {us.get('user_id')}")
            click.echo(f"  Kullanım:    {us.get('used_mb', 0):.2f} MB / {us.get('limit_gb', 10):.2f} GB ({us.get('usage_percent', 0):.2f}%)")
    except Exception as e:
        click.echo(f"✗ Bellek durumu alınamadı: {e}", err=True)


@memory_group.command("index")
def memory_index():
    """Bellek indeksini yenile."""
    click.echo("Bellek indeksleniyor...")
    try:
        from core.memory import MemoryManager
        mm = MemoryManager()
        if asyncio.iscoroutinefunction(mm.rebuild_index):
            asyncio.run(mm.rebuild_index())
        else:
            mm.rebuild_index()
        click.echo("✓ İndeks güncellendi.")
    except Exception as e:
        click.echo(f"✗ İndeks güncellenemedi: {e}", err=True)


@memory_group.command("search")
@click.argument("query")
@click.option("--limit", default=10, help="Sonuç sayısı")
@click.option("--user", default=None, type=int, help="Kullanıcı ID filtresi")
def memory_search(query, limit, user):
    """Bellekte semantik arama yap."""
    click.echo(f"Aranıyor: '{query}'...")
    try:
        from core.memory import MemoryManager
        mm = MemoryManager()
        if asyncio.iscoroutinefunction(mm.search):
            results = asyncio.run(mm.search(query, limit=limit, user_id=user))
        else:
            results = mm.search(query, limit=limit, user_id=user)

        if not results:
            click.echo("Sonuç bulunamadı.")
            return

        for i, r in enumerate(results, 1):
            click.echo(f"\n[{i}] {r.get('content', '')[:120]}")
            click.echo(f"    Tarih: {r.get('timestamp', '-')} | Skor: {r.get('score', 0):.2f}")
    except Exception as e:
        click.echo(f"✗ Arama başarısız: {e}", err=True)


@memory_group.command("export")
@click.option("--format", "fmt", default="json", type=click.Choice(["json", "markdown"]), help="Çıktı formatı")
@click.option("--output", "-o", default=None, help="Çıktı dosyası")
def memory_export(fmt, output):
    """Belleği dışa aktar."""
    try:
        from core.memory import MemoryManager
        mm = MemoryManager()
        if asyncio.iscoroutinefunction(mm.export):
            data = asyncio.run(mm.export(format=fmt))
        else:
            data = mm.export(format=fmt)

        if output:
            with open(output, "w", encoding="utf-8") as f:
                f.write(data if isinstance(data, str) else json.dumps(data, indent=2, ensure_ascii=False))
            click.echo(f"✓ Bellek dışa aktarıldı: {output}")
        else:
            click.echo(data if isinstance(data, str) else json.dumps(data, indent=2, ensure_ascii=False))
    except Exception as e:
        click.echo(f"✗ Dışa aktarma başarısız: {e}", err=True)


@memory_group.command("clear")
@click.option("--user", default=None, type=int, help="Sadece bu kullanıcının belleğini temizle")
@click.confirmation_option(prompt="Belleği silmek istediğinizden emin misiniz?")
def memory_clear(user):
    """Belleği temizle."""
    try:
        from core.memory import MemoryManager
        mm = MemoryManager()
        if asyncio.iscoroutinefunction(mm.clear):
            asyncio.run(mm.clear(user_id=user))
        else:
            mm.clear(user_id=user)
        scope = f"Kullanıcı {user}" if user else "Tüm"
        click.echo(f"✓ {scope} bellek temizlendi.")
    except Exception as e:
        click.echo(f"✗ Temizleme başarısız: {e}", err=True)


@memory_group.command("stats")
@click.option("--user", default=None, type=int, help="Kullanıcı ID filtresi")
def memory_stats(user):
    """Bellek istatistiklerini göster."""
    try:
        from core.memory import MemoryManager
        mm = MemoryManager()
        if asyncio.iscoroutinefunction(mm.get_stats):
            stats = asyncio.run(mm.get_stats(user_id=user))
        else:
            stats = mm.get_stats(user_id=user)
        click.echo(json.dumps(stats, indent=2, ensure_ascii=False))
    except Exception as e:
        click.echo(f"✗ {e}", err=True)


def register(cli):
    cli.add_command(memory_group, name="memory")


# ── Argparse uyumlu wrapper (cli/main.py için) ───────────────────────
def run(args):
    """argparse args'tan gelen subcommand'ı ilgili fonksiyona yönlendir."""
    sub = getattr(args, "subcommand", None)
    if not sub or sub == "status":
        _run_status(user=getattr(args, "user", None))
    elif sub == "index":
        _run_index()
    elif sub == "search":
        query = getattr(args, "query", None) or ""
        _run_search(query, user=getattr(args, "user", None))
    elif sub == "export":
        _run_export(fmt=getattr(args, "format", "json"), output=getattr(args, "file", None))
    elif sub == "clear":
        _run_clear(user=getattr(args, "user", None))
    elif sub == "stats":
        _run_stats(user=getattr(args, "user", None))
    elif sub == "import":
        _run_import(getattr(args, "file", None))
    else:
        print("Usage: elyan memory [status|index|search|export|import|clear|stats]")


def _to_int_or_none(value):
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _run_status(user=None):
    try:
        from core.memory import MemoryManager
        mm = MemoryManager()
        user_id = _to_int_or_none(user)
        stats = asyncio.run(mm.get_stats(user_id=user_id)) if asyncio.iscoroutinefunction(mm.get_stats) else mm.get_stats(user_id=user_id)
        print(f"Bellek Durumu")
        print(f"  Toplam öğe: {stats.get('total_items', 0)}")
        print(f"  Boyut:      {stats.get('size_mb', 0):.1f} MB")
        print(f"  Yol:        {stats.get('path', '~/.elyan/memory/')}")
        if stats.get("user_storage"):
            us = stats["user_storage"]
            print(f"  Kullanıcı:  {us.get('user_id')}")
            print(f"  Kullanım:   {us.get('used_mb', 0):.2f} MB / {us.get('limit_gb', 10):.2f} GB ({us.get('usage_percent', 0):.2f}%)")
    except Exception as e:
        print(f"Bellek durumu alınamadı: {e}")


def _run_index():
    print("Bellek indeksleniyor...")
    try:
        from core.memory import MemoryManager
        mm = MemoryManager()
        if asyncio.iscoroutinefunction(mm.rebuild_index):
            asyncio.run(mm.rebuild_index())
        else:
            mm.rebuild_index()
        print("✅  İndeks güncellendi.")
    except Exception as e:
        print(f"Hata: {e}")


def _run_search(query: str, user=None):
    print(f"Aranıyor: '{query}'...")
    try:
        from core.memory import MemoryManager
        mm = MemoryManager()
        results = asyncio.run(mm.search(query, limit=10, user_id=user)) if asyncio.iscoroutinefunction(mm.search) else mm.search(query, limit=10, user_id=user)
        for i, r in enumerate(results or [], 1):
            print(f"\n[{i}] {str(r.get('content',''))[:120]}")
            print(f"    Tarih: {r.get('timestamp','-')} | Skor: {r.get('score',0):.2f}")
        if not results:
            print("Sonuç bulunamadı.")
    except Exception as e:
        print(f"Hata: {e}")


def _run_export(fmt: str = "json", output=None):
    try:
        from core.memory import MemoryManager
        mm = MemoryManager()
        data = asyncio.run(mm.export(format=fmt)) if asyncio.iscoroutinefunction(mm.export) else mm.export(format=fmt)
        text = data if isinstance(data, str) else json.dumps(data, indent=2, ensure_ascii=False)
        if output:
            open(output, "w", encoding="utf-8").write(text)
            print(f"✅  Dışa aktarıldı: {output}")
        else:
            print(text)
    except Exception as e:
        print(f"Hata: {e}")


def _run_clear(user=None):
    confirm = input("⚠️  Bellek silinecek. Devam? (evet/hayır): ").strip().lower()
    if confirm != "evet":
        print("İptal edildi.")
        return
    try:
        from core.memory import MemoryManager
        mm = MemoryManager()
        if asyncio.iscoroutinefunction(mm.clear):
            asyncio.run(mm.clear(user_id=user))
        else:
            mm.clear(user_id=user)
        print(f"✅  {'Kullanıcı ' + str(user) if user else 'Tüm'} bellek temizlendi.")
    except Exception as e:
        print(f"Hata: {e}")


def _run_stats(user=None):
    try:
        from core.memory import MemoryManager
        mm = MemoryManager()
        user_id = _to_int_or_none(user)
        stats = asyncio.run(mm.get_stats(user_id=user_id)) if asyncio.iscoroutinefunction(mm.get_stats) else mm.get_stats(user_id=user_id)
        print(json.dumps(stats, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"Hata: {e}")


def _run_import(file_path):
    if not file_path:
        print("Hata: dosya yolu gereklidir.")
        return
    print(f"İçe aktarılıyor: {file_path}")
    try:
        import pathlib
        data = json.loads(pathlib.Path(file_path).read_text(encoding="utf-8"))
        from core.memory import MemoryManager
        mm = MemoryManager()
        if hasattr(mm, "import_data"):
            result = asyncio.run(mm.import_data(data)) if asyncio.iscoroutinefunction(mm.import_data) else mm.import_data(data)
            print(f"✅  İçe aktarıldı: {result}")
        else:
            print("⚠️  MemoryManager import_data desteklemiyor.")
    except Exception as e:
        print(f"Hata: {e}")
