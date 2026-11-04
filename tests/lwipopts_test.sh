#!/bin/sh
set -eu

source_file=$(mktemp)
trap 'rm -f "$source_file"' EXIT HUP INT TERM

check_pool_sizes()
{
	heap=$1
	send=$2
	window=$3
	scale=$4
	connections=$5
	segments=$6
	pbufs=$7

	cat > "$source_file" <<EOF
	#include <sys/types.h>
	#include <unistd.h>
	#include "lwip/opt.h"
_Static_assert(OCPROXY_BUFFERED_CONNECTIONS == $connections, "buffered connections");
_Static_assert(MEMP_NUM_TCP_SEG == $segments, "TCP segment pool target");
_Static_assert(PBUF_POOL_SIZE == $pbufs, "packet buffer pool target");
EOF

	$CC -std=c11 -D_DEFAULT_SOURCE -fsyntax-only -x c $LWIP_CPPFLAGS \
		-DOCPROXY_HEAP_BYTES="$heap" \
		-DOCPROXY_TCP_SND_BYTES="$send" \
		-DOCPROXY_TCP_WND_BYTES="$window" \
		-DOCPROXY_TCP_RCV_SCALE="$scale" \
		"$source_file"
}

check_pool_sizes 67108864 262144 262144 3 64 16384 8192
check_pool_sizes 16777216 131072 131072 2 32 4096 2048

cat > "$source_file" <<'EOF'
#include <sys/types.h>
#include <unistd.h>
#include "lwip/opt.h"
EOF
if $CC -std=c11 -D_DEFAULT_SOURCE -fsyntax-only -x c $LWIP_CPPFLAGS \
	-DOCPROXY_TCP_WND_BYTES=262144 \
	-DOCPROXY_TCP_RCV_SCALE=2 \
	"$source_file" >/dev/null 2>&1; then
	echo "invalid TCP window configuration was accepted" >&2
	exit 1
fi
