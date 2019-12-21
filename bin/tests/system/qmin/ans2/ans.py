############################################################################
# Copyright (C) Internet Systems Consortium, Inc. ("ISC")
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# See the COPYRIGHT file distributed with this work for additional
# information regarding copyright ownership.
############################################################################

from __future__ import print_function
import os
import sys
import signal
import socket
import select
from datetime import datetime, timedelta
import time
import functools

import dns, dns.message, dns.query, dns.flags
from dns.rdatatype import *
from dns.rdataclass import *
from dns.rcode import *
from dns.name import *


# Log query to file
def logquery(type, qname):
    with open("qlog", "a") as f:
        f.write("%s %s\n", type, qname)

############################################################################
# Respond to a DNS query.
# For good. it serves:
# ns2.good. IN A 10.53.0.2
# zoop.boing.good. NS ns3.good.
# ns3.good. IN A 10.53.0.3
# too.many.labels.a.b.c.d.e.f.g.h.i.j.k.l.m.n.o.p.q.r.s.t.u.v.w.x.y.z.good. A 192.0.2.2
# it responds properly (with NODATA empty response) to non-empty terminals
#
# For slow. it works the same as for good., but each response is delayed by 400 miliseconds
#
# For bad. it works the same as for good., but returns NXDOMAIN to non-empty terminals
#
# For ugly. it works the same as for good., but returns garbage to non-empty terminals
#
# For 1.0.0.2.ip6.arpa it serves
# 1.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.8.f.4.0.1.0.0.2.ip6.arpa. IN PTR nee.com.
# 1.0.0.2.ip6.arpa. IN NS ns2.good
# ip6.arpa. IN NS ns2.good
############################################################################
def create_response(msg):
    m = dns.message.from_wire(msg)
    qname = m.question[0].name.to_text()
    lqname = qname.lower()
    labels = lqname.split('.')

    # get qtype
    rrtype = m.question[0].rdtype
    typename = dns.rdatatype.to_text(rrtype)
    if typename == "A" or typename == "AAAA":
        typename = "ADDR"
    bad = False
    ugly = False
    slow = False

    # log this query
    with open("query.log", "a") as f:
        f.write("%s %s\n" % (typename, lqname))
        print("%s %s" % (typename, lqname), end=" ")

    r = dns.message.make_response(m)
    r.set_rcode(NOERROR)

    if lqname.endswith("1.0.0.2.ip6.arpa."):
        # Direct query - give direct answer
        if lqname == "1.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.8.f.4.0.1.0.0.2.ip6.arpa." and rrtype == PTR:
            # Direct query - give direct answer
            r.answer.append(dns.rrset.from_text("1.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.8.f.4.0.1.0.0.2.ip6.arpa.", 1, IN, PTR, "nee.com."))
            r.flags |= dns.flags.AA
        elif lqname == "1.0.0.2.ip6.arpa." and rrtype == NS:
            # NS query at the apex
            r.answer.append(dns.rrset.from_text("1.0.0.2.ip6.arpa.", 1, IN, NS, "ns2.good."))
            r.flags |= dns.flags.AA
        elif "1.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.8.f.4.0.1.0.0.2.ip6.arpa.".endswith(lqname):
            # NODATA answer
            r.authority.append(dns.rrset.from_text("1.0.0.2.ip6.arpa.", 1, IN, SOA, "ns2.good. hostmaster.arpa. 2018050100 1 1 1 1"))
        else:
            # NXDOMAIN
            r.authority.append(dns.rrset.from_text("1.0.0.2.ip6.arpa.", 1, IN, SOA, "ns2.good. hostmaster.arpa. 2018050100 1 1 1 1"))
            r.set_rcode(NXDOMAIN)
        return r
    elif lqname.endswith("ip6.arpa."):
        if lqname == "ip6.arpa." and rrtype == NS:
            # NS query at the apex
            r.answer.append(dns.rrset.from_text("ip6.arpa.", 1, IN, NS, "ns2.good."))
            r.flags |= dns.flags.AA
        elif "1.0.0.2.ip6.arpa.".endswith(lqname):
            # NODATA answer
            r.authority.append(dns.rrset.from_text("ip6.arpa.", 1, IN, SOA, "ns2.good. hostmaster.arpa. 2018050100 1 1 1 1"))
        else:
            # NXDOMAIN
            r.authority.append(dns.rrset.from_text("ip6.arpa.", 1, IN, SOA, "ns2.good. hostmaster.arpa. 2018050100 1 1 1 1"))
            r.set_rcode(NXDOMAIN)
        return r
    elif lqname.endswith("bad."):
        bad = True
        suffix = "bad."
        lqname = lqname[:-4]
    elif lqname.endswith("ugly."):
        ugly = True
        suffix = "ugly."
        lqname = lqname[:-5]
    elif lqname.endswith("good."):
        suffix = "good."
        lqname = lqname[:-5]
    elif lqname.endswith("slow."):
        slow = True
        suffix = "slow."
        lqname = lqname[:-5]
    elif lqname.endswith("fwd."):
        suffix = "fwd."
        lqname = lqname[:-4]
    else:
        r.set_rcode(REFUSED)
        return r

    # Good/bad/ugly differs only in how we treat non-empty terminals
    if lqname.endswith("zoop.boing."):
        r.authority.append(dns.rrset.from_text("zoop.boing." + suffix, 1, IN, NS, "ns3." + suffix))
    elif lqname == "many.labels.a.b.c.d.e.f.g.h.i.j.k.l.m.n.o.p.q.r.s.t.u.v.w.x.y.z." and rrtype == A:
        r.answer.append(dns.rrset.from_text(lqname + suffix, 1, IN, A, "192.0.2.2"))
        r.flags |= dns.flags.AA
    elif lqname == "" and rrtype == NS:
        r.answer.append(dns.rrset.from_text(suffix, 1, IN, NS, "ns2." + suffix))
        r.flags |= dns.flags.AA
    elif lqname == "ns2." and rrtype == A:
        r.answer.append(dns.rrset.from_text("ns2."+suffix, 1, IN, A, "10.53.0.2"))
        r.flags |= dns.flags.AA
    elif lqname == "ns2." and rrtype == AAAA:
        r.answer.append(dns.rrset.from_text("ns2."+suffix, 1, IN, AAAA, "fd92:7065:b8e:ffff::2"))
        r.flags |= dns.flags.AA
    elif lqname == "ns3." and rrtype == A:
        r.answer.append(dns.rrset.from_text("ns3."+suffix, 1, IN, A, "10.53.0.3"))
        r.flags |= dns.flags.AA
    elif lqname == "ns3." and rrtype == AAAA:
        r.answer.append(dns.rrset.from_text("ns3."+suffix, 1, IN, AAAA, "fd92:7065:b8e:ffff::3"))
        r.flags |= dns.flags.AA
    elif lqname == "a.bit.longer.ns.name." and rrtype == A:
        r.answer.append(dns.rrset.from_text("a.bit.longer.ns.name."+suffix, 1, IN, A, "10.53.0.4"))
        r.flags |= dns.flags.AA
    elif lqname == "a.bit.longer.ns.name." and rrtype == AAAA:
        r.answer.append(dns.rrset.from_text("a.bit.longer.ns.name."+suffix, 1, IN, AAAA, "fd92:7065:b8e:ffff::4"))
        r.flags |= dns.flags.AA
    else:
        r.authority.append(dns.rrset.from_text(suffix, 1, IN, SOA, "ns2." + suffix + " hostmaster.arpa. 2018050100 1 1 1 1"))
        if bad or not \
            ("icky.icky.icky.ptang.zoop.boing.".endswith(lqname) or \
             "many.labels.a.b.c.d.e.f.g.h.i.j.k.l.m.n.o.p.q.r.s.t.u.v.w.x.y.z.".endswith(lqname) or \
             "a.bit.longer.ns.name.".endswith(lqname)):
            r.set_rcode(NXDOMAIN)
        if ugly:
            r.set_rcode(FORMERR)
    if slow:
        time.sleep(0.2)
    return r


def sigterm(signum, frame):
    print ("Shutting down now...")
    os.remove('ans.pid')
    running = False
    sys.exit(0)

############################################################################
# Main
#
# Set up responder and control channel, open the pid file, and start
# the main loop, listening for queries on the query channel or commands
# on the control channel and acting on them.
############################################################################
ip4 = "10.53.0.2"
ip6 = "fd92:7065:b8e:ffff::2"

try: port=int(os.environ['PORT'])
except: port=5300

query4_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
query4_socket.bind((ip4, port))

havev6 = True
try:
    query6_socket = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
    try:
        query6_socket.bind((ip6, port))
    except:
        query6_socket.close()
        havev6 = False
except:
    havev6 = False

signal.signal(signal.SIGTERM, sigterm)

f = open('ans.pid', 'w')
pid = os.getpid()
print (pid, file=f)
f.close()

running = True

print ("Listening on %s port %d" % (ip4, port))
if havev6:
    print ("Listening on %s port %d" % (ip6, port))
print ("Ctrl-c to quit")

if havev6:
    input = [query4_socket, query6_socket]
else:
    input = [query4_socket]

while running:
    try:
        inputready, outputready, exceptready = select.select(input, [], [])
    except select.error as e:
        break
    except socket.error as e:
        break
    except KeyboardInterrupt:
        break

    for s in inputready:
        if s == query4_socket or s == query6_socket:
            print ("Query received on %s" %
                    (ip4 if s == query4_socket else ip6), end=" ")
            # Handle incoming queries
            msg = s.recvfrom(65535)
            rsp = create_response(msg[0])
            if rsp:
                print(dns.rcode.to_text(rsp.rcode()))
                s.sendto(rsp.to_wire(), msg[1])
            else:
                print("NO RESPONSE")
    if not running:
        break
