using System;

namespace MCPForUnity.Editor
{
    /// <summary>
    /// Ontelic build of MCP for Unity: this package never connects outside this PC.
    /// Every outbound path of the upstream package (update check, skill sync, NuGet installer, asset generation,
    /// remote login, WebSocket/HTTP transport, server launch, AI client config rewrite) checks this lock.
    /// Ontelic talks to the editor over the local socket (127.0.0.1) the stdio bridge already opens.
    /// See NOTICE.ontelic.md next to this package.
    /// </summary>
    public static class OntelicLock
    {
        public static readonly bool Offline = true;

        public const string Why =
            "Ontelic build: outbound network, server launch and AI client registration are disabled. " +
            "Connect Claude or Codex from Ontelic settings instead.";

        public static InvalidOperationException Blocked(string what)
        {
            return new InvalidOperationException("ontelic_offline: " + what + " - " + Why);
        }
    }
}
