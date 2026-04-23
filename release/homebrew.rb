class Elyan < Formula
  desc "Elyan v1: self-hosted privacy-first AI answering engine"
  homepage "https://elyan.dev"
  url "https://registry.npmjs.org/elyan/-/elyan-1.0.0.tgz"
  sha256 "1eb9937e55960105158ad889f5c63e984b3660013e7c458418326a2a762d70ba"
  version "1.0.0"

  depends_on "node"

  def install
    libexec.install Dir["*"]
    system "npm", "install", "--omit=dev", *Language::Node.std_npm_install_args(libexec)

    bin.install_symlink libexec/"bin/elyan.js" => "elyan"
  end

  def caveats
    <<~EOS
      Elyan runs directly as a Node.js app for the main local path.
      SearxNG is optional. If you want live web retrieval and citations, run a local SearxNG instance and point SEARXNG_URL to it.
      Hosted identity and billing are optional and require NEXTAUTH_SECRET plus iyzico credentials.
      MCP integration is optional and stays outside the core launch path.
      To launch the release after configuring .env:

        elyan start
    EOS
  end

  test do
    assert_match "Usage: elyan", shell_output("#{bin}/elyan --help")
  end
end
