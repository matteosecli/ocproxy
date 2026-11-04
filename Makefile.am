AUTOMAKE_OPTIONS	= foreign subdir-objects

AM_CFLAGS		= @WFLAGS@ -Dunix -DIPv4 \
			  -I$(srcdir)/lwip/src/include \
			  -I$(srcdir)/src

# lwIP is built in NO_SYS mode (raw API only); see src/lwipopts.h
LWIP_SOURCES		:= \
			   lwip/src/core/def.c \
			   lwip/src/core/dns.c \
			   lwip/src/core/inet_chksum.c \
			   lwip/src/core/init.c \
			   lwip/src/core/ip.c \
			   lwip/src/core/mem.c \
			   lwip/src/core/memp.c \
			   lwip/src/core/netif.c \
			   lwip/src/core/pbuf.c \
			   lwip/src/core/stats.c \
			   lwip/src/core/sys.c \
			   lwip/src/core/tcp.c \
			   lwip/src/core/tcp_in.c \
			   lwip/src/core/tcp_out.c \
			   lwip/src/core/timeouts.c \
			   lwip/src/core/udp.c \
			   lwip/src/core/ipv4/icmp.c \
			   lwip/src/core/ipv4/ip4.c \
			   lwip/src/core/ipv4/ip4_addr.c \
			   lwip/src/core/ipv4/ip4_frag.c

APP_SOURCES		:= src/ocproxy.c src/lwipopts.h src/arch/cc.h

bin_PROGRAMS		= ocproxy
ocproxy_SOURCES		= $(LWIP_SOURCES) $(APP_SOURCES)

dist_man_MANS		= ocproxy.1
dist_doc_DATA		= README.md CHANGES
dist_noinst_SCRIPTS	= autogen.sh

if ENABLE_VPNNS
vpnns_SOURCES		= src/vpnns.c
bin_PROGRAMS		+= vpnns
dist_man_MANS		+= vpnns.1
endif

TESTS			= tests/e2e_test.py
TESTS_ENVIRONMENT	= OCPROXY=$(abs_builddir)/ocproxy

EXTRA_DIST		= .gitignore tests/e2e_test.py
DISTCLEANFILES		= *~

# Copy from $(srcdir) only: with subdir-objects, a plain EXTRA_DIST entry for
# lwip/ would also pick up the object files from the build directory.
dist-hook:
	mkdir -p $(distdir)/lwip && cp -R $(srcdir)/lwip/. $(distdir)/lwip/
	chmod -R u+w $(distdir)/lwip

LWIP_GIT		= https://github.com/lwip-tcpip/lwip.git
LWIP_GIT_TAG		= STABLE-2_2_1_RELEASE

.PHONY: update-lwip
update-lwip:
	rm -rf lwip lwip-upstream.tmp
	git clone $(LWIP_GIT) lwip-upstream.tmp
	cd lwip-upstream.tmp && git checkout $(LWIP_GIT_TAG)
	mkdir lwip
	cp -r lwip-upstream.tmp/src lwip-upstream.tmp/COPYING \
		lwip-upstream.tmp/README lwip-upstream.tmp/UPGRADING \
		lwip-upstream.tmp/CHANGELOG lwip/
	cd lwip-upstream.tmp && git rev-parse HEAD > ../lwip/VERSION
	echo $(LWIP_GIT_TAG) >> lwip/VERSION
	rm -rf lwip-upstream.tmp
