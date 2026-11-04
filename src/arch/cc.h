#ifndef OCPROXY_ARCH_CC_H
#define OCPROXY_ARCH_CC_H

/* Minimal lwIP port for a single-threaded (NO_SYS=1) unix build. */

#include <errno.h>
#include <stdlib.h>
#include <sys/time.h>
#include <sys/types.h>

#define LWIP_ERRNO_INCLUDE	<errno.h>
#define LWIP_ERRNO_STDINCLUDE	1

/* the system headers already provide htons() & friends */
#define LWIP_DONT_PROVIDE_BYTEORDER_FUNCTIONS

/* seeded in main() */
#define LWIP_RAND()		((u32_t)random())

#endif /* OCPROXY_ARCH_CC_H */
