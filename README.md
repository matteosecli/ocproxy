## Upload throughput fix on macOS (and small-buffer systems)

The backpressure fix and throughput measurements below were contributed by
Jian Zhou in [upstream PR #33](https://github.com/cernekee/ocproxy/pull/33),
developed in [jzthree/ocproxy](https://github.com/jzthree/ocproxy). This fork
incorporates that contribution.

Before that fix, ocproxy silently **dropped upstream packets** when the
`--script-tun` socketpair to openconnect was full (`lwip_data_out` counted a
link-level drop and moved on). On macOS the socketpair holds only ~2 datagrams
(`net.local.dgram.recvspace` = 4 KB), so any upload burst overflows it; lwIP
then stalls in ~1 s retransmission timeouts and uploads collapse to roughly
one send window per second — **~60 KB/s measured, while downloads ran at
4 MB/s** on the same VPN.

The contribution adds lossless backpressure: on `EAGAIN`/`ENOBUFS` the packet
is queued (bounded FIFO) and flushed when the fd turns writable. It also
hardens the VPN read path (`EAGAIN` is not a dead VPN, and the old code fell
through to `pbuf_alloc()` with a negative length after `vpn_conn_down()`).

As reported with the contribution, on a production AnyConnect VPN (macOS arm64):
uploads **61 KB/s → 1.9 MB/s** (single stream) and **3.8 MB/s sustained**;
downloads unchanged. Linux is less affected (~200 KB default buffers) but
the drop-instead-of-backpressure behavior is the same.

---

ocproxy
=======

ocproxy is a user-level SOCKS and port forwarding proxy for
[OpenConnect](http://www.infradead.org/openconnect/)
based on lwIP.  When using ocproxy, OpenConnect only handles network
activity that the user specifically asks to proxy, so the VPN interface
no longer "hijacks" all network traffic on the host.

Basic usage
-----------

Commonly used options include:

      -D port                   Set up a SOCKS5 server on PORT
      -H port                   Set up an HTTP proxy server on PORT
      -L lport:rhost:rport      Connections to localhost:LPORT will be redirected
                                over the VPN to RHOST:RPORT
      -l file, --logfile file   Log all proxy requests to FILE
      -g                        Allow non-local clients.
      -k interval               Send TCP keepalive every INTERVAL seconds, to
                                prevent connection timeouts

ocproxy should not be run directly.  Instead, it should be started by
openconnect using the --script-tun option:

    openconnect --script-tun --script \
        "./ocproxy -L 2222:unix-host:22 -L 3389:win-host:3389 -D 11080" \
        vpn.example.com

You can also use the HTTP proxy with `-H`:

    openconnect --script-tun --script \
        "./ocproxy -H 8080 -D 11080" \
        vpn.example.com

Once ocproxy is running, connections can be established over the VPN link
by connecting directly to a forwarded port or by utilizing the builtin
SOCKS or HTTP proxy servers:

    ssh -p2222 localhost
    rdesktop localhost
    socksify ssh unix-host
    tsocks ssh 172.16.1.2
    ...

OpenConnect can (and should) be run as a non-root user when using ocproxy.


Logging
-------

Connection logging and the documentation in this section were contributed by
Miroslav Hostinsky.

ocproxy can log all proxy requests to a file using the `-l` or `--logfile` option:

    openconnect --script-tun --script \
        "./ocproxy -H 8080 -D 11080 -l /var/log/ocproxy.log" \
        vpn.example.com

The log file will contain timestamped entries for all connection requests through the proxy:

**Log format examples:**

    [2025-01-15 14:23:45] HTTP GET -> http://example.com/page.html
    [2025-01-15 14:23:46] HTTPS CONNECT -> https://secure.example.com:443/
    [2025-01-15 14:23:47] SOCKS5 -> mail.example.com:993
    [2025-01-15 14:23:48] PORT-FWD -> internal-server:22

The log includes:
- **Timestamp** in format `YYYY-MM-DD HH:MM:SS`
- **Protocol type**: HTTP, HTTPS, SOCKS5, or PORT-FWD
- **HTTP method** for HTTP requests (GET, POST, PUT, DELETE, etc.)
- **Full URL** for HTTP/HTTPS requests
- **Destination hostname/IP and port** for all connection types

The log file is opened in append mode, so logs persist across multiple ocproxy sessions.


Using the HTTP proxy
---------------------

HTTP proxy support was introduced by bman in
[upstream PR #30](https://github.com/cernekee/ocproxy/pull/30), from
[bmansvk/ocproxy](https://github.com/bmansvk/ocproxy). Miroslav Hostinsky
contributed subsequent HTTP proxy enhancements.

The HTTP proxy supports both regular HTTP methods (GET, POST, PUT, DELETE, etc.)
and the CONNECT method for tunneling HTTPS connections. This provides full
HTTP/HTTPS proxy functionality.

You can configure your browser or other applications to use the HTTP proxy
for both HTTP and HTTPS connections.

To configure the HTTP proxy in your browser:
- Set HTTP proxy to 127.0.0.1 port 8080 (or the port specified with -H)
- Set HTTPS proxy to the same address and port

The HTTP proxy can be used alongside the SOCKS5 proxy. Some applications
may work better with HTTP proxy (browsers), while others may prefer SOCKS5.

Supported features:
- Full HTTP/1.x proxy with all standard methods (GET, POST, PUT, DELETE, HEAD, OPTIONS, etc.)
- HTTPS tunneling via CONNECT method
- Both absolute URLs (http://host/path) and relative URLs with Host header
- Automatic DNS resolution for hostnames
- HTTP keep-alive connections


Using the SOCKS5 proxy
----------------------

tsocks, Dante, or similar wrappers can be used with non-SOCKS-aware
applications.

Sample tsocks.conf (no DNS):

    server = 127.0.0.1
    server_type = 5
    server_port = 11080

Sample socks.conf for Dante (DNS lookups via SOCKS5 "DOMAIN" addresses):

    resolveprotocol: fake
    route {
            from: 0.0.0.0/0 to: 0.0.0.0/0 via: 127.0.0.1 port = 11080
            command: connect
            proxyprotocol: socks_v5
    }

[FoxyProxy](http://getfoxyproxy.org/) can be used to tunnel Firefox or Chrome
browsing through the SOCKS5 server.  This will send DNS queries through the
VPN connection, and unqualified internal hostnames (e.g. http://intranet/)
should work.  FoxyProxy also allows the user to route requests based on URL
patterns, so that (for instance) certain domains always use the proxy server
but all other traffic connects directly.

It is possible to start several different instances of Firefox, each with
its own separate profile (and hence, proxy settings):

    # initial setup
    firefox -no-remote -ProfileManager

    # run with previous configured profile "vpn"
    firefox -no-remote -P vpn


Building ocproxy
----------------

Dependencies:

 * libevent &gt;= 2.0: *.so library and headers
 * autoconf
 * automake
 * gcc, binutils, make, etc.

Building from git on Linux:

    ./autogen.sh
    ./configure
    make

Building from git on macOS:

First, install dependencies using Homebrew:

    brew install libevent automake autoconf

Then build with the correct library paths:

    ./autogen.sh
    ./configure \
      CPPFLAGS="-I/opt/homebrew/opt/libevent/include" \
      LDFLAGS="-L/opt/homebrew/opt/libevent/lib"
    make

Note: For Intel Macs, use `/usr/local` instead of `/opt/homebrew`:

    ./configure \
      CPPFLAGS="-I/usr/local/opt/libevent/include" \
      LDFLAGS="-L/usr/local/opt/libevent/lib"

Run the test suite (a self-contained end-to-end test; needs only python3):

    make check

Pre-built binaries (Linux and macOS, amd64 and arm64) are attached to each
[release](https://github.com/matteosecli/ocproxy/releases).

lwIP memory and TCP window tuning:

By default ocproxy is built with a 64 MiB lwIP heap and 256 KiB TCP send
buffers / receive windows (with TCP window scaling, shift 3).  These can be
overridden at configure time, e.g.:

    ./configure CPPFLAGS="-DOCPROXY_HEAP_BYTES=33554432 \
                          -DOCPROXY_TCP_SND_BYTES=131072 \
                          -DOCPROXY_TCP_WND_BYTES=131072 \
                          -DOCPROXY_TCP_RCV_SCALE=2"

The build fails if the window is not representable with the chosen scale
(`TCP_WND <= 65535 << TCP_RCV_SCALE`).  See `src/lwipopts.h`.

The lwIP TCP segment and packet-buffer pool targets scale with those settings.
They account for a number of fully buffered connections that fits within half
the configured heap, capped by the TCP PCB count; the remaining heap is
reserved for stack metadata and allocator overhead. Because lwIP is configured
to allocate these pools dynamically from its fixed heap, these pool values are
accounting targets, not independent allocation limits. The heap is the actual
memory limit, and TCP may retransmit if it is exhausted.

lwIP (currently 2.2.1) is bundled in `lwip/`; `make update-lwip` refreshes it.
Note that the `-T`/`--tcpdump` option was removed, since the lwIP 2.x
sources no longer ship the tcpdump helper.


Other possible uses for ocproxy
-------------------------------

 * Routing traffic from different applications/browsers through different VPNs
(or no VPN)
 * Connecting to multiple VPNs or sites concurrently, even if their IP ranges
overlap or their DNS settings are incompatible
 * Situations in which root access is unavailable or undesirable; multiuser
systems

It is possible to write a proxy autoconfig (PAC) script that decides whether
each request should use ocproxy or a direct connection, based on the domain
or other criteria.

ocproxy also works with OpenVPN; the necessary patches are posted
[here](http://thread.gmane.org/gmane.network.openvpn.devel/8478).


Network configuration
---------------------

ocproxy normally reads its network configuration from the following
environment variables set by OpenConnect:

 * `INTERNAL_IP4_ADDRESS`: IPv4 address
 * `INTERNAL_IP4_MTU`: interface MTU
 * `INTERNAL_IP4_DNS`: DNS server list (optional but recommended)
 * `CISCO_DEF_DOMAIN`: default domain name (optional)

The `VPNFD` environment variable tells ocproxy which file descriptor is used
to pass the tunneled traffic.


vpnns (experimental)
--------------------

Another approach to solving this problem is to create a separate network
namespace (netns).  This is supported by Linux kernels &gt;= v3.8.

This starts up an application in a fresh user/net/uts/mount namespace:

    vpnns -- google-chrome --user-data-dir=/tmp/vpntest
    
    vpnns -- firefox -no-remote -P vpn

    vpnns -- transmission-gtk

Initially it will not have any network access as the only interface
present in the netns is the loopback device.  The application should still
be able to talk to Xorg through UNIX sockets in /tmp.

The next step is to connect to a VPN and invoke `vpnns --attach` to pass
the VPN traffic back and forth:

    openconnect --script "vpnns --attach" --script-tun vpn.example.com

    openvpn --script-security 2 --config example.ovpn \
            --dev "|HOME=$HOME vpnns --attach"

These commands connect to an ocserv or openvpn gateway, then tell vpnns
to set up a tunnel device, default route, and resolv.conf inside the
namespace created above.  On success, the web browser will have connectivity.
When the VPN disconnects, the browser will lose all connectivity, preventing
leaks.

`vpnns` can be rerun multiple times if the connection fails or if the VPN
client crashes.  If run without arguments, it will open a shell inside the
namespace.

Some differences between vpnns and ocproxy:

 * No proxies are involved, so apps should not require any special
configuration.
 * vpnns is better-suited for hard-to-proxy protocols such as VOIP or
BitTorrent.
 * vpnns will only ever run on Linux.
 * vpnns may interfere with dbus connections.

Unlike previous approaches to the problem (e.g. anything that involves
running `ip netns`), vpnns does not require root privileges or changing
the host network configuration.

The `--name` option allows additional (and separate) namespaces to be
created.

If your X server is a version that uses abstract sockets only (and UNIX
sockets in /tmp are disabled), you can re-enable UNIX sockets by adding
`-listen unix` to `/etc/X11/xinit/xserverrc`.

<!-- TODO: re-enable once a PPA is available for this fork.
The OpenVPN example requires out-of-tree patches.  Updated openvpn and
ocproxy packages are available for Ubuntu 14.04 LTS and 16.04 LTS:

    sudo -s
    apt-get install software-properties-common
    add-apt-repository --yes ppa:cernekee
    apt-get update
    apt-get install ocproxy openvpn
-->


Credits
-------

Original author: David Edmondson &lt;dme@dme.org&gt;

Current maintainer: Kevin Cernekee &lt;cernekee@gmail.com&gt;

Contributions incorporated from upstream:

 * [GitHub Security Lab, PR #14](https://github.com/cernekee/ocproxy/pull/14)
   ([ghsecuritylab/ocproxy](https://github.com/ghsecuritylab/ocproxy)):
   security fix for the PPP hostname buffer.
 * [genisysram, PR #18](https://github.com/cernekee/ocproxy/pull/18)
   ([genisysram/ocproxy](https://github.com/genisysram/ocproxy)):
   ppc64le architecture support.
 * [Herwig Hochleitner, PR #21](https://github.com/cernekee/ocproxy/pull/21)
   ([bendlas/ocproxy](https://github.com/bendlas/ocproxy)):
   configurable UID/GID mappings for vpnns.
 * [bman, PR #30](https://github.com/cernekee/ocproxy/pull/30)
   ([bmansvk/ocproxy](https://github.com/bmansvk/ocproxy)):
   HTTP proxy support.
 * [Jian Zhou, PR #33](https://github.com/cernekee/ocproxy/pull/33)
   ([jzthree/ocproxy](https://github.com/jzthree/ocproxy)):
   lossless backpressure for VPN socketpair writes.

Additional HTTP proxy and connection-logging enhancements were contributed by
Miroslav Hostinsky.

Fork home page: https://github.com/matteosecli/ocproxy

Original project: https://github.com/cernekee/ocproxy
