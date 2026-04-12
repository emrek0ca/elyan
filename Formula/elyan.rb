class Elyan < Formula
  include Language::Python::Virtualenv

  desc "Local-first personal AI operator runtime"
  homepage "https://github.com/emrek0ca/elyan"
  url "https://github.com/emrek0ca/elyan/archive/refs/heads/main.tar.gz"
  version "20.1.0"
  sha256 :no_check
  license "MIT"

  depends_on "python@3.11"

  def install
    venv = virtualenv_create(libexec, "python3.11")
    system libexec/"bin/python", "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"
    system libexec/"bin/python", "-m", "pip", "install", buildpath
    bin.install_symlink libexec/"bin/elyan"
  end

  def caveats
    <<~EOS
      Elyan runs on http://127.0.0.1:18789 by default.

      First run:
        cp #{HOMEBREW_PREFIX}/opt/elyan/.env.example .env 2>/dev/null || true
        elyan start --port 18789

      Optional local model runtime:
        brew install ollama
        ollama serve
        ollama pull llama3.2:3b
    EOS
  end

  test do
    system "#{bin}/elyan", "--version"
  end
end
