#!/usr/bin/env python3
"""Second wave of arena practice tasks — harder, and closer to the project's own domains.

The v1 suite of 100 tasks was solved roughly nine times over, which stopped
being a source of new signal for CORE: the ceiling was the catalogue, not the
arena. These tasks raise the floor. They stay inside the same contract — pure,
offline, deterministic Python, no clock, no network, no host path — but ask for
real parsing, real algorithms and the network/sysadmin reasoning this project
actually needs.

Same shape as the v1 list: (slug, function_name, prompt, reference_solution,
[assert lines]). The reference solution never ships; it only proves here that
the task is solvable and that its tests are self-consistent.

Tasks are appended, never inserted: ids are positional, and packets already
built reference arena-001..100.
"""

from __future__ import annotations

_PARSING: list[tuple[str, str, str, str, list[str]]] = [
    # --- parsing et formats -------------------------------------------------
    ("parse-ini", "parse_ini",
     "Write parse_ini(text) that parses INI text into a dict of section -> dict of key -> value. "
     "Lines starting with ; or # are comments, blank lines are ignored, keys and values are stripped. "
     "Keys before any section header belong to the section ''.",
     "def parse_ini(text):\n"
     "    out = {}\n"
     "    section = ''\n"
     "    out[section] = {}\n"
     "    for raw in text.splitlines():\n"
     "        line = raw.strip()\n"
     "        if not line or line[0] in ';#':\n"
     "            continue\n"
     "        if line.startswith('[') and line.endswith(']'):\n"
     "            section = line[1:-1].strip()\n"
     "            out.setdefault(section, {})\n"
     "            continue\n"
     "        if '=' in line:\n"
     "            key, value = line.split('=', 1)\n"
     "            out[section][key.strip()] = value.strip()\n"
     "    if not out['']:\n"
     "        del out['']\n"
     "    return out",
     ["assert module['parse_ini']('[a]\\nx = 1\\n; c\\ny=2') == {'a': {'x': '1', 'y': '2'}}",
      "assert module['parse_ini']('k=v\\n[s]\\nn=1') == {'': {'k': 'v'}, 's': {'n': '1'}}",
      "assert module['parse_ini']('') == {}"]),

    ("parse-semver", "parse_semver",
     "Write parse_semver(version) that splits a semantic version like '1.2.3-beta.1' into the tuple "
     "(major, minor, patch, prerelease) where the first three are ints and prerelease is a string "
     "('' when absent). Raise ValueError if the version is malformed.",
     "def parse_semver(version):\n"
     "    core, _, pre = version.partition('-')\n"
     "    parts = core.split('.')\n"
     "    if len(parts) != 3:\n"
     "        raise ValueError('malformed version')\n"
     "    numbers = []\n"
     "    for part in parts:\n"
     "        if not part.isdigit():\n"
     "            raise ValueError('malformed version')\n"
     "        numbers.append(int(part))\n"
     "    return (numbers[0], numbers[1], numbers[2], pre)",
     ["assert module['parse_semver']('1.2.3') == (1, 2, 3, '')",
      "assert module['parse_semver']('0.10.0-rc.2') == (0, 10, 0, 'rc.2')",
      "try:\n    module['parse_semver']('1.2')\n    raise AssertionError('should raise')\nexcept ValueError:\n    pass"]),

    ("compare-versions", "compare_versions",
     "Write compare_versions(a, b) that compares two dotted numeric versions and returns -1, 0 or 1. "
     "Missing components count as zero, so '1.2' equals '1.2.0'.",
     "def compare_versions(a, b):\n"
     "    pa = [int(x) for x in a.split('.')]\n"
     "    pb = [int(x) for x in b.split('.')]\n"
     "    size = max(len(pa), len(pb))\n"
     "    pa += [0] * (size - len(pa))\n"
     "    pb += [0] * (size - len(pb))\n"
     "    return (pa > pb) - (pa < pb)",
     ["assert module['compare_versions']('1.2', '1.2.0') == 0",
      "assert module['compare_versions']('1.10', '1.9') == 1",
      "assert module['compare_versions']('2.0', '10.0') == -1"]),

    ("parse-cookie", "parse_cookie",
     "Write parse_cookie(header) that parses a Cookie header like 'a=1; b=2' into a dict. "
     "Pairs are separated by ';', names and values are stripped, and a pair without '=' is ignored.",
     "def parse_cookie(header):\n"
     "    out = {}\n"
     "    for piece in header.split(';'):\n"
     "        if '=' not in piece:\n"
     "            continue\n"
     "        name, value = piece.split('=', 1)\n"
     "        name = name.strip()\n"
     "        if name:\n"
     "            out[name] = value.strip()\n"
     "    return out",
     ["assert module['parse_cookie']('a=1; b=2') == {'a': '1', 'b': '2'}",
      "assert module['parse_cookie']('sid=xyz; broken; k=') == {'sid': 'xyz', 'k': ''}",
      "assert module['parse_cookie']('') == {}"]),

    ("parse-syslog", "parse_syslog",
     "Write parse_syslog(line) that splits a syslog line like '<34>Oct 11 22:14:15 host app: message' "
     "into the dict {'priority': 34, 'host': 'host', 'tag': 'app', 'message': 'message'}. "
     "Return None if the line does not start with a <priority>.",
     "def parse_syslog(line):\n"
     "    if not line.startswith('<') or '>' not in line:\n"
     "        return None\n"
     "    end = line.index('>')\n"
     "    priority = line[1:end]\n"
     "    if not priority.isdigit():\n"
     "        return None\n"
     "    rest = line[end + 1:]\n"
     "    parts = rest.split(' ', 4)\n"
     "    if len(parts) < 5:\n"
     "        return None\n"
     "    host = parts[3]\n"
     "    tail = parts[4]\n"
     "    tag, _, message = tail.partition(': ')\n"
     "    return {'priority': int(priority), 'host': host, 'tag': tag, 'message': message}",
     ["assert module['parse_syslog']('<34>Oct 11 22:14:15 web01 sshd: failed login') == "
      "{'priority': 34, 'host': 'web01', 'tag': 'sshd', 'message': 'failed login'}",
      "assert module['parse_syslog']('no priority here at all') is None",
      "assert module['parse_syslog']('<x>Oct 11 22:14:15 h a: m') is None"]),

    ("parse-http-request-line", "parse_request_line",
     "Write parse_request_line(line) that splits an HTTP request line such as 'GET /a?b=1 HTTP/1.1' "
     "into (method, path, query, version). The query excludes the '?' and is '' when absent. "
     "Return None when the line does not have exactly three space-separated parts.",
     "def parse_request_line(line):\n"
     "    parts = line.split(' ')\n"
     "    if len(parts) != 3:\n"
     "        return None\n"
     "    method, target, version = parts\n"
     "    path, _, query = target.partition('?')\n"
     "    return (method, path, query, version)",
     ["assert module['parse_request_line']('GET /a?b=1 HTTP/1.1') == ('GET', '/a', 'b=1', 'HTTP/1.1')",
      "assert module['parse_request_line']('POST /submit HTTP/1.0') == ('POST', '/submit', '', 'HTTP/1.0')",
      "assert module['parse_request_line']('GET /only-two-parts') is None"]),

    ("parse-header-block", "parse_headers",
     "Write parse_headers(text) that parses HTTP header lines into a dict with lowercase names. "
     "A header repeated several times has its values joined with ', '. Lines without ':' are ignored.",
     "def parse_headers(text):\n"
     "    out = {}\n"
     "    for line in text.splitlines():\n"
     "        if ':' not in line:\n"
     "            continue\n"
     "        name, value = line.split(':', 1)\n"
     "        key = name.strip().lower()\n"
     "        value = value.strip()\n"
     "        out[key] = value if key not in out else out[key] + ', ' + value\n"
     "    return out",
     ["assert module['parse_headers']('Host: a\\nAccept: b') == {'host': 'a', 'accept': 'b'}",
      "assert module['parse_headers']('Set-Cookie: a\\nSet-Cookie: b') == {'set-cookie': 'a, b'}",
      "assert module['parse_headers']('garbage') == {}"]),

    ("split-csv-quoted", "split_csv_quoted",
     "Write split_csv_quoted(line) that splits a CSV line on commas, honouring double quotes. "
     "A quoted field may contain commas, and a doubled quote inside a quoted field means one quote. "
     "Surrounding quotes are removed.",
     "def split_csv_quoted(line):\n"
     "    fields = []\n"
     "    current = []\n"
     "    in_quotes = False\n"
     "    index = 0\n"
     "    while index < len(line):\n"
     "        char = line[index]\n"
     "        if in_quotes:\n"
     "            if char == '\"':\n"
     "                if index + 1 < len(line) and line[index + 1] == '\"':\n"
     "                    current.append('\"')\n"
     "                    index += 1\n"
     "                else:\n"
     "                    in_quotes = False\n"
     "            else:\n"
     "                current.append(char)\n"
     "        elif char == '\"':\n"
     "            in_quotes = True\n"
     "        elif char == ',':\n"
     "            fields.append(''.join(current))\n"
     "            current = []\n"
     "        else:\n"
     "            current.append(char)\n"
     "        index += 1\n"
     "    fields.append(''.join(current))\n"
     "    return fields",
     ["assert module['split_csv_quoted']('a,b,c') == ['a', 'b', 'c']",
      "assert module['split_csv_quoted']('a,\"b,c\",d') == ['a', 'b,c', 'd']",
      "assert module['split_csv_quoted']('\"he said \"\"hi\"\"\",x') == ['he said \"hi\"', 'x']"]),

    ("parse-size", "parse_size",
     "Write parse_size(text) that converts a size such as '10K', '2.5M' or '512' into a number of bytes "
     "as an int, using binary units (K=1024, M=1024**2, G=1024**3, T=1024**4). The suffix is "
     "case-insensitive. Raise ValueError on an unknown suffix.",
     "def parse_size(text):\n"
     "    units = {'K': 1024, 'M': 1024 ** 2, 'G': 1024 ** 3, 'T': 1024 ** 4}\n"
     "    text = text.strip()\n"
     "    if not text:\n"
     "        raise ValueError('empty size')\n"
     "    last = text[-1].upper()\n"
     "    if last.isdigit():\n"
     "        return int(float(text))\n"
     "    if last not in units:\n"
     "        raise ValueError('unknown unit')\n"
     "    return int(float(text[:-1]) * units[last])",
     ["assert module['parse_size']('512') == 512",
      "assert module['parse_size']('10K') == 10240",
      "assert module['parse_size']('2.5m') == 2621440",
      "try:\n    module['parse_size']('4X')\n    raise AssertionError('should raise')\nexcept ValueError:\n    pass"]),

    ("format-table", "format_table",
     "Write format_table(rows) that renders a list of equal-length string rows as lines where every "
     "column is left-padded to the widest cell in that column and columns are joined by a single space. "
     "Trailing spaces are stripped from each line. Return [] for no rows.",
     "def format_table(rows):\n"
     "    if not rows:\n"
     "        return []\n"
     "    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]\n"
     "    lines = []\n"
     "    for row in rows:\n"
     "        line = ' '.join(cell.ljust(widths[i]) for i, cell in enumerate(row))\n"
     "        lines.append(line.rstrip())\n"
     "    return lines",
     ["assert module['format_table']([['a', 'bbb'], ['cc', 'd']]) == ['a  bbb', 'cc d']",
      "assert module['format_table']([]) == []",
      "assert module['format_table']([['x']]) == ['x']"]),
]

_NETWORK: list[tuple[str, str, str, str, list[str]]] = [
    ("cidr-contains", "cidr_contains",
     "Write cidr_contains(cidr, ip) that returns True when the IPv4 address ip lies inside the CIDR block "
     "cidr (for example '10.0.0.0/8'). Both are dotted-quad strings; do not import any module.",
     "def cidr_contains(cidr, ip):\n"
     "    network, _, bits = cidr.partition('/')\n"
     "    prefix = int(bits)\n"
     "    def to_int(value):\n"
     "        a, b, c, d = (int(x) for x in value.split('.'))\n"
     "        return (a << 24) | (b << 16) | (c << 8) | d\n"
     "    mask = (0xFFFFFFFF << (32 - prefix)) & 0xFFFFFFFF if prefix else 0\n"
     "    return to_int(network) & mask == to_int(ip) & mask",
     ["assert module['cidr_contains']('10.0.0.0/8', '10.1.2.3') is True",
      "assert module['cidr_contains']('192.168.1.0/24', '192.168.2.1') is False",
      "assert module['cidr_contains']('0.0.0.0/0', '8.8.8.8') is True"]),

    ("cidr-overlap", "cidr_overlap",
     "Write cidr_overlap(a, b) that returns True when two IPv4 CIDR blocks share at least one address.",
     "def cidr_overlap(a, b):\n"
     "    def parse(cidr):\n"
     "        network, _, bits = cidr.partition('/')\n"
     "        prefix = int(bits)\n"
     "        parts = [int(x) for x in network.split('.')]\n"
     "        value = (parts[0] << 24) | (parts[1] << 16) | (parts[2] << 8) | parts[3]\n"
     "        mask = (0xFFFFFFFF << (32 - prefix)) & 0xFFFFFFFF if prefix else 0\n"
     "        return value & mask, mask\n"
     "    net_a, mask_a = parse(a)\n"
     "    net_b, mask_b = parse(b)\n"
     "    shared = mask_a & mask_b\n"
     "    return net_a & shared == net_b & shared",
     ["assert module['cidr_overlap']('10.0.0.0/8', '10.1.0.0/16') is True",
      "assert module['cidr_overlap']('192.168.0.0/24', '192.168.1.0/24') is False",
      "assert module['cidr_overlap']('0.0.0.0/0', '172.16.0.0/12') is True"]),

    ("prefix-from-netmask", "prefix_from_netmask",
     "Write prefix_from_netmask(mask) that converts a dotted IPv4 netmask into its prefix length. "
     "Raise ValueError when the mask is not a run of ones followed by zeros.",
     "def prefix_from_netmask(mask):\n"
     "    parts = [int(x) for x in mask.split('.')]\n"
     "    if len(parts) != 4 or any(p < 0 or p > 255 for p in parts):\n"
     "        raise ValueError('bad mask')\n"
     "    bits = ''.join(format(p, '08b') for p in parts)\n"
     "    stripped = bits.rstrip('0')\n"
     "    if '0' in stripped:\n"
     "        raise ValueError('non contiguous mask')\n"
     "    return len(stripped)",
     ["assert module['prefix_from_netmask']('255.255.255.0') == 24",
      "assert module['prefix_from_netmask']('0.0.0.0') == 0",
      "try:\n    module['prefix_from_netmask']('255.0.255.0')\n    raise AssertionError('should raise')\nexcept ValueError:\n    pass"]),

    ("broadcast-address", "broadcast_address",
     "Write broadcast_address(cidr) that returns the broadcast address of an IPv4 CIDR block as a "
     "dotted-quad string.",
     "def broadcast_address(cidr):\n"
     "    network, _, bits = cidr.partition('/')\n"
     "    prefix = int(bits)\n"
     "    parts = [int(x) for x in network.split('.')]\n"
     "    value = (parts[0] << 24) | (parts[1] << 16) | (parts[2] << 8) | parts[3]\n"
     "    mask = (0xFFFFFFFF << (32 - prefix)) & 0xFFFFFFFF if prefix else 0\n"
     "    last = (value & mask) | (~mask & 0xFFFFFFFF)\n"
     "    return '.'.join(str((last >> shift) & 255) for shift in (24, 16, 8, 0))",
     ["assert module['broadcast_address']('192.168.1.0/24') == '192.168.1.255'",
      "assert module['broadcast_address']('10.0.0.0/8') == '10.255.255.255'",
      "assert module['broadcast_address']('1.2.3.4/32') == '1.2.3.4'"]),

    ("summarize-ports", "summarize_ports",
     "Write summarize_ports(ports) that turns a list of port numbers into a sorted, compact string of "
     "ranges, for example [22, 80, 81, 82] -> '22,80-82'. Duplicates collapse. Return '' for an empty list.",
     "def summarize_ports(ports):\n"
     "    values = sorted(set(ports))\n"
     "    if not values:\n"
     "        return ''\n"
     "    pieces = []\n"
     "    start = previous = values[0]\n"
     "    for value in values[1:]:\n"
     "        if value == previous + 1:\n"
     "            previous = value\n"
     "            continue\n"
     "        pieces.append(str(start) if start == previous else f'{start}-{previous}')\n"
     "        start = previous = value\n"
     "    pieces.append(str(start) if start == previous else f'{start}-{previous}')\n"
     "    return ','.join(pieces)",
     ["assert module['summarize_ports']([22, 80, 81, 82]) == '22,80-82'",
      "assert module['summarize_ports']([]) == ''",
      "assert module['summarize_ports']([5, 5, 4]) == '4-5'"]),

    ("expand-port-range", "expand_port_range",
     "Write expand_port_range(spec) that expands a specification like '22,80-82' into a sorted list of "
     "unique ints. Raise ValueError when a range is reversed or a piece is not numeric.",
     "def expand_port_range(spec):\n"
     "    out = set()\n"
     "    for piece in spec.split(','):\n"
     "        piece = piece.strip()\n"
     "        if not piece:\n"
     "            continue\n"
     "        if '-' in piece:\n"
     "            low, _, high = piece.partition('-')\n"
     "            if not low.isdigit() or not high.isdigit():\n"
     "                raise ValueError('bad range')\n"
     "            if int(low) > int(high):\n"
     "                raise ValueError('reversed range')\n"
     "            out.update(range(int(low), int(high) + 1))\n"
     "        else:\n"
     "            if not piece.isdigit():\n"
     "                raise ValueError('bad port')\n"
     "            out.add(int(piece))\n"
     "    return sorted(out)",
     ["assert module['expand_port_range']('22,80-82') == [22, 80, 81, 82]",
      "assert module['expand_port_range']('') == []",
      "try:\n    module['expand_port_range']('90-80')\n    raise AssertionError('should raise')\nexcept ValueError:\n    pass"]),

    ("normalize-mac", "normalize_mac",
     "Write normalize_mac(mac) that normalises a MAC address written with ':', '-' or '.' separators "
     "into lowercase colon-separated form. Raise ValueError when it does not hold exactly 12 hex digits.",
     "def normalize_mac(mac):\n"
     "    digits = ''.join(c for c in mac if c not in ':-.')\n"
     "    if len(digits) != 12 or any(c not in '0123456789abcdefABCDEF' for c in digits):\n"
     "        raise ValueError('bad mac')\n"
     "    digits = digits.lower()\n"
     "    return ':'.join(digits[i:i + 2] for i in range(0, 12, 2))",
     ["assert module['normalize_mac']('AA-BB-CC-DD-EE-FF') == 'aa:bb:cc:dd:ee:ff'",
      "assert module['normalize_mac']('aabb.ccdd.eeff') == 'aa:bb:cc:dd:ee:ff'",
      "try:\n    module['normalize_mac']('aa:bb')\n    raise AssertionError('should raise')\nexcept ValueError:\n    pass"]),

    ("mac-is-multicast", "mac_is_multicast",
     "Write mac_is_multicast(mac) that returns True when the least significant bit of the first octet "
     "of a colon-separated MAC address is set, which marks a multicast frame.",
     "def mac_is_multicast(mac):\n"
     "    first = int(mac.split(':')[0], 16)\n"
     "    return bool(first & 1)",
     ["assert module['mac_is_multicast']('01:00:5e:00:00:01') is True",
      "assert module['mac_is_multicast']('aa:bb:cc:dd:ee:ff') is False",
      "assert module['mac_is_multicast']('ff:ff:ff:ff:ff:ff') is True"]),

    ("ipv4-class", "ipv4_class",
     "Write ipv4_class(ip) that returns the classful letter of an IPv4 address: 'A' for 0-127, "
     "'B' for 128-191, 'C' for 192-223, 'D' for 224-239 and 'E' for 240-255, based on the first octet.",
     "def ipv4_class(ip):\n"
     "    first = int(ip.split('.')[0])\n"
     "    if first < 128:\n"
     "        return 'A'\n"
     "    if first < 192:\n"
     "        return 'B'\n"
     "    if first < 224:\n"
     "        return 'C'\n"
     "    if first < 240:\n"
     "        return 'D'\n"
     "    return 'E'",
     ["assert module['ipv4_class']('10.0.0.1') == 'A'",
      "assert module['ipv4_class']('192.168.0.1') == 'C'",
      "assert module['ipv4_class']('240.0.0.1') == 'E'"]),

    ("is-private-ip", "is_private_ip",
     "Write is_private_ip(ip) that returns True when an IPv4 address is in 10.0.0.0/8, 172.16.0.0/12 "
     "or 192.168.0.0/16.",
     "def is_private_ip(ip):\n"
     "    a, b = (int(x) for x in ip.split('.')[:2])\n"
     "    if a == 10:\n"
     "        return True\n"
     "    if a == 172 and 16 <= b <= 31:\n"
     "        return True\n"
     "    return a == 192 and b == 168",
     ["assert module['is_private_ip']('10.255.0.1') is True",
      "assert module['is_private_ip']('172.32.0.1') is False",
      "assert module['is_private_ip']('192.168.4.4') is True"]),

    ("octets-to-cidr-list", "split_prefix",
     "Write split_prefix(cidr, count) that splits an IPv4 CIDR block into `count` equal subnets and "
     "returns their CIDR strings in order. count must be a power of two, otherwise raise ValueError.",
     "def split_prefix(cidr, count):\n"
     "    if count < 1 or count & (count - 1):\n"
     "        raise ValueError('count must be a power of two')\n"
     "    network, _, bits = cidr.partition('/')\n"
     "    prefix = int(bits)\n"
     "    added = count.bit_length() - 1\n"
     "    new_prefix = prefix + added\n"
     "    if new_prefix > 32:\n"
     "        raise ValueError('prefix too long')\n"
     "    parts = [int(x) for x in network.split('.')]\n"
     "    base = (parts[0] << 24) | (parts[1] << 16) | (parts[2] << 8) | parts[3]\n"
     "    step = 1 << (32 - new_prefix)\n"
     "    out = []\n"
     "    for index in range(count):\n"
     "        value = base + index * step\n"
     "        dotted = '.'.join(str((value >> shift) & 255) for shift in (24, 16, 8, 0))\n"
     "        out.append(f'{dotted}/{new_prefix}')\n"
     "    return out",
     ["assert module['split_prefix']('10.0.0.0/8', 2) == ['10.0.0.0/9', '10.128.0.0/9']",
      "assert module['split_prefix']('192.168.1.0/24', 4)[3] == '192.168.1.192/26'",
      "try:\n    module['split_prefix']('10.0.0.0/8', 3)\n    raise AssertionError('should raise')\nexcept ValueError:\n    pass"]),

    ("luhn-check", "luhn_check",
     "Write luhn_check(digits) that returns True when a string of digits satisfies the Luhn checksum. "
     "Return False when the string is empty or contains a non-digit.",
     "def luhn_check(digits):\n"
     "    if not digits or any(c not in '0123456789' for c in digits):\n"
     "        return False\n"
     "    total = 0\n"
     "    for index, char in enumerate(reversed(digits)):\n"
     "        value = int(char)\n"
     "        if index % 2 == 1:\n"
     "            value *= 2\n"
     "            if value > 9:\n"
     "                value -= 9\n"
     "        total += value\n"
     "    return total % 10 == 0",
     ["assert module['luhn_check']('79927398713') is True",
      "assert module['luhn_check']('79927398710') is False",
      "assert module['luhn_check']('12a4') is False"]),

    ("checksum16", "checksum16",
     "Write checksum16(data) that computes the one's-complement 16-bit Internet checksum of a bytes "
     "object, as used by IP headers, and returns it as an int. Pad with a zero byte when the length is odd.",
     "def checksum16(data):\n"
     "    if len(data) % 2:\n"
     "        data = data + b'\\x00'\n"
     "    total = 0\n"
     "    for index in range(0, len(data), 2):\n"
     "        total += (data[index] << 8) | data[index + 1]\n"
     "        total = (total & 0xFFFF) + (total >> 16)\n"
     "    return (~total) & 0xFFFF",
     ["assert module['checksum16'](b'\\x00\\x00') == 0xFFFF",
      "assert module['checksum16'](b'\\xff\\xff') == 0",
      "assert isinstance(module['checksum16'](b'abc'), int)"]),

    ("password-strength", "password_strength",
     "Write password_strength(password) that scores a password from 0 to 5: one point each for length "
     "at least 12, a lowercase letter, an uppercase letter, a digit, and a character that is none of "
     "those three classes.",
     "def password_strength(password):\n"
     "    score = 0\n"
     "    if len(password) >= 12:\n"
     "        score += 1\n"
     "    if any(c.islower() for c in password):\n"
     "        score += 1\n"
     "    if any(c.isupper() for c in password):\n"
     "        score += 1\n"
     "    if any(c.isdigit() for c in password):\n"
     "        score += 1\n"
     "    if any(not (c.islower() or c.isupper() or c.isdigit()) for c in password):\n"
     "        score += 1\n"
     "    return score",
     ["assert module['password_strength']('abc') == 1",
      "assert module['password_strength']('Corr3ct!Horse42') == 5",
      "assert module['password_strength']('') == 0"]),

    ("symbolic-to-octal", "symbolic_to_octal",
     "Write symbolic_to_octal(mode) that converts a 9-character symbolic Unix mode such as 'rwxr-xr--' "
     "into its octal string, here '754'. Raise ValueError when the length is not 9.",
     "def symbolic_to_octal(mode):\n"
     "    if len(mode) != 9:\n"
     "        raise ValueError('mode must be 9 characters')\n"
     "    out = ''\n"
     "    for start in (0, 3, 6):\n"
     "        chunk = mode[start:start + 3]\n"
     "        value = 0\n"
     "        if chunk[0] == 'r':\n"
     "            value += 4\n"
     "        if chunk[1] == 'w':\n"
     "            value += 2\n"
     "        if chunk[2] == 'x':\n"
     "            value += 1\n"
     "        out += str(value)\n"
     "    return out",
     ["assert module['symbolic_to_octal']('rwxr-xr--') == '754'",
      "assert module['symbolic_to_octal']('---------') == '000'",
      "try:\n    module['symbolic_to_octal']('rwx')\n    raise AssertionError('should raise')\nexcept ValueError:\n    pass"]),

    ("apply-umask", "apply_umask",
     "Write apply_umask(mode, umask) that takes two octal strings such as '666' and '022' and returns "
     "the resulting octal permission string after the umask bits are cleared.",
     "def apply_umask(mode, umask):\n"
     "    result = int(mode, 8) & ~int(umask, 8)\n"
     "    return format(result, '03o')",
     ["assert module['apply_umask']('666', '022') == '644'",
      "assert module['apply_umask']('777', '077') == '700'",
      "assert module['apply_umask']('644', '000') == '644'"]),

    ("glob-match", "glob_match",
     "Write glob_match(pattern, name) that matches a shell-style pattern against a name, supporting "
     "'*' for any run of characters and '?' for exactly one. Do not import any module.",
     "def glob_match(pattern, name):\n"
     "    rows = len(pattern)\n"
     "    cols = len(name)\n"
     "    table = [[False] * (cols + 1) for _ in range(rows + 1)]\n"
     "    table[0][0] = True\n"
     "    for i in range(1, rows + 1):\n"
     "        if pattern[i - 1] == '*':\n"
     "            table[i][0] = table[i - 1][0]\n"
     "    for i in range(1, rows + 1):\n"
     "        for j in range(1, cols + 1):\n"
     "            char = pattern[i - 1]\n"
     "            if char == '*':\n"
     "                table[i][j] = table[i - 1][j] or table[i][j - 1]\n"
     "            elif char == '?' or char == name[j - 1]:\n"
     "                table[i][j] = table[i - 1][j - 1]\n"
     "    return table[rows][cols]",
     ["assert module['glob_match']('*.log', 'syslog.log') is True",
      "assert module['glob_match']('a?c', 'abc') is True",
      "assert module['glob_match']('a?c', 'ac') is False",
      "assert module['glob_match']('*', '') is True"]),

    ("acl-decision", "acl_decision",
     "Write acl_decision(rules, port) that walks a list of (action, low, high) rules in order, where "
     "action is 'allow' or 'deny', and returns the action of the first rule whose inclusive range "
     "contains port. Return 'deny' when no rule matches.",
     "def acl_decision(rules, port):\n"
     "    for action, low, high in rules:\n"
     "        if low <= port <= high:\n"
     "            return action\n"
     "    return 'deny'",
     ["assert module['acl_decision']([('allow', 80, 80), ('deny', 0, 65535)], 80) == 'allow'",
      "assert module['acl_decision']([('allow', 80, 80), ('deny', 0, 65535)], 22) == 'deny'",
      "assert module['acl_decision']([], 443) == 'deny'"]),

    ("rate-limit-allows", "rate_limit_allows",
     "Write rate_limit_allows(timestamps, window, limit) that returns the list of booleans saying, for "
     "each timestamp in the ascending list, whether the request is allowed: a request is allowed when "
     "fewer than `limit` requests were already allowed within the preceding `window` (inclusive).",
     "def rate_limit_allows(timestamps, window, limit):\n"
     "    allowed_times = []\n"
     "    out = []\n"
     "    for now in timestamps:\n"
     "        allowed_times = [t for t in allowed_times if now - t < window]\n"
     "        if len(allowed_times) < limit:\n"
     "            allowed_times.append(now)\n"
     "            out.append(True)\n"
     "        else:\n"
     "            out.append(False)\n"
     "    return out",
     ["assert module['rate_limit_allows']([0, 1, 2], 10, 2) == [True, True, False]",
      "assert module['rate_limit_allows']([0, 20, 40], 10, 1) == [True, True, True]",
      "assert module['rate_limit_allows']([], 5, 1) == []"]),

    ("rot13-alpha", "rot13",
     "Write rot13(text) that applies the ROT13 substitution to ASCII letters and leaves every other "
     "character untouched. Do not import any module.",
     "def rot13(text):\n"
     "    out = []\n"
     "    for char in text:\n"
     "        if 'a' <= char <= 'z':\n"
     "            out.append(chr((ord(char) - 97 + 13) % 26 + 97))\n"
     "        elif 'A' <= char <= 'Z':\n"
     "            out.append(chr((ord(char) - 65 + 13) % 26 + 65))\n"
     "        else:\n"
     "            out.append(char)\n"
     "    return ''.join(out)",
     ["assert module['rot13']('Hello, World!') == 'Uryyb, Jbeyq!'",
      "assert module['rot13'](module['rot13']('round trip')) == 'round trip'",
      "assert module['rot13']('') == ''"]),

    ("vigenere-encrypt", "vigenere",
     "Write vigenere(text, key) that applies a Vigenere shift to lowercase letters a-z using a "
     "lowercase key, leaving other characters unchanged and not advancing the key on them.",
     "def vigenere(text, key):\n"
     "    out = []\n"
     "    index = 0\n"
     "    for char in text:\n"
     "        if 'a' <= char <= 'z':\n"
     "            shift = ord(key[index % len(key)]) - 97\n"
     "            out.append(chr((ord(char) - 97 + shift) % 26 + 97))\n"
     "            index += 1\n"
     "        else:\n"
     "            out.append(char)\n"
     "    return ''.join(out)",
     ["assert module['vigenere']('attack', 'lemon') == 'lxfopv'",
      "assert module['vigenere']('a b', 'b') == 'b c'",
      "assert module['vigenere']('', 'key') == ''"]),

    ("hex-dump-line", "hex_dump",
     "Write hex_dump(data) that renders bytes as lines of at most 16 bytes, each line being the offset "
     "in 8 hex digits, a space, the bytes as two-digit lowercase hex separated by spaces, then two "
     "spaces and the printable ASCII (32..126) with other bytes shown as '.'.",
     "def hex_dump(data):\n"
     "    lines = []\n"
     "    for start in range(0, len(data), 16):\n"
     "        chunk = data[start:start + 16]\n"
     "        hexes = ' '.join(format(b, '02x') for b in chunk)\n"
     "        text = ''.join(chr(b) if 32 <= b <= 126 else '.' for b in chunk)\n"
     "        lines.append(f'{start:08x} {hexes}  {text}')\n"
     "    return lines",
     ["assert module['hex_dump'](b'AB') == ['00000000 41 42  AB']",
      "assert module['hex_dump'](b'') == []",
      "assert module['hex_dump'](b'\\x00')[0].endswith('  .')"]),
]

_ALGORITHMS: list[tuple[str, str, str, str, list[str]]] = [
    ("merge-intervals", "merge_intervals",
     "Write merge_intervals(intervals) that merges a list of [start, end] pairs into the shortest sorted "
     "list of non-overlapping intervals. Touching intervals like [1,2] and [2,3] merge into [1,3].",
     "def merge_intervals(intervals):\n"
     "    out = []\n"
     "    for start, end in sorted(intervals):\n"
     "        if out and start <= out[-1][1]:\n"
     "            out[-1][1] = max(out[-1][1], end)\n"
     "        else:\n"
     "            out.append([start, end])\n"
     "    return out",
     ["assert module['merge_intervals']([[1, 3], [2, 6], [8, 10]]) == [[1, 6], [8, 10]]",
      "assert module['merge_intervals']([[1, 2], [2, 3]]) == [[1, 3]]",
      "assert module['merge_intervals']([]) == []"]),

    ("interval-gaps", "interval_gaps",
     "Write interval_gaps(intervals, start, end) that returns the sorted list of [a, b] gaps inside "
     "[start, end] that no interval covers. Intervals may overlap and are not sorted.",
     "def interval_gaps(intervals, start, end):\n"
     "    merged = []\n"
     "    for low, high in sorted(intervals):\n"
     "        if merged and low <= merged[-1][1]:\n"
     "            merged[-1][1] = max(merged[-1][1], high)\n"
     "        else:\n"
     "            merged.append([low, high])\n"
     "    gaps = []\n"
     "    cursor = start\n"
     "    for low, high in merged:\n"
     "        if low > cursor:\n"
     "            gaps.append([cursor, min(low, end)])\n"
     "        cursor = max(cursor, high)\n"
     "        if cursor >= end:\n"
     "            break\n"
     "    if cursor < end:\n"
     "        gaps.append([cursor, end])\n"
     "    return [g for g in gaps if g[0] < g[1]]",
     ["assert module['interval_gaps']([[1, 3], [6, 8]], 0, 10) == [[0, 1], [3, 6], [8, 10]]",
      "assert module['interval_gaps']([], 0, 5) == [[0, 5]]",
      "assert module['interval_gaps']([[0, 10]], 0, 10) == []"]),

    ("edit-distance", "edit_distance",
     "Write edit_distance(a, b) that returns the Levenshtein distance between two strings, counting "
     "insertions, deletions and substitutions as one each.",
     "def edit_distance(a, b):\n"
     "    previous = list(range(len(b) + 1))\n"
     "    for i, ca in enumerate(a, start=1):\n"
     "        current = [i]\n"
     "        for j, cb in enumerate(b, start=1):\n"
     "            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))\n"
     "        previous = current\n"
     "    return previous[-1]",
     ["assert module['edit_distance']('kitten', 'sitting') == 3",
      "assert module['edit_distance']('', 'abc') == 3",
      "assert module['edit_distance']('same', 'same') == 0"]),

    ("longest-common-subsequence", "lcs_length",
     "Write lcs_length(a, b) that returns the length of the longest common subsequence of two strings.",
     "def lcs_length(a, b):\n"
     "    previous = [0] * (len(b) + 1)\n"
     "    for ca in a:\n"
     "        current = [0]\n"
     "        for j, cb in enumerate(b, start=1):\n"
     "            current.append(previous[j - 1] + 1 if ca == cb else max(previous[j], current[j - 1]))\n"
     "        previous = current\n"
     "    return previous[-1]",
     ["assert module['lcs_length']('abcde', 'ace') == 3",
      "assert module['lcs_length']('abc', 'xyz') == 0",
      "assert module['lcs_length']('', '') == 0"]),

    ("longest-increasing", "longest_increasing",
     "Write longest_increasing(values) that returns the length of the longest strictly increasing "
     "subsequence of a list of numbers.",
     "def longest_increasing(values):\n"
     "    tails = []\n"
     "    for value in values:\n"
     "        low, high = 0, len(tails)\n"
     "        while low < high:\n"
     "            mid = (low + high) // 2\n"
     "            if tails[mid] < value:\n"
     "                low = mid + 1\n"
     "            else:\n"
     "                high = mid\n"
     "        if low == len(tails):\n"
     "            tails.append(value)\n"
     "        else:\n"
     "            tails[low] = value\n"
     "    return len(tails)",
     ["assert module['longest_increasing']([10, 9, 2, 5, 3, 7, 101, 18]) == 4",
      "assert module['longest_increasing']([]) == 0",
      "assert module['longest_increasing']([3, 3, 3]) == 1"]),

    ("max-subarray", "max_subarray",
     "Write max_subarray(values) that returns the largest sum obtainable from a non-empty contiguous "
     "slice of the list. Return 0 for an empty list.",
     "def max_subarray(values):\n"
     "    if not values:\n"
     "        return 0\n"
     "    best = current = values[0]\n"
     "    for value in values[1:]:\n"
     "        current = max(value, current + value)\n"
     "        best = max(best, current)\n"
     "    return best",
     ["assert module['max_subarray']([-2, 1, -3, 4, -1, 2, 1, -5, 4]) == 6",
      "assert module['max_subarray']([-5, -2, -9]) == -2",
      "assert module['max_subarray']([]) == 0"]),

    ("two-sum-indices", "two_sum",
     "Write two_sum(values, target) that returns the pair of indices (i, j) with i < j whose values add "
     "up to target, choosing the pair with the smallest i then the smallest j. Return None when there "
     "is none.",
     "def two_sum(values, target):\n"
     "    for i in range(len(values)):\n"
     "        for j in range(i + 1, len(values)):\n"
     "            if values[i] + values[j] == target:\n"
     "                return (i, j)\n"
     "    return None",
     ["assert module['two_sum']([2, 7, 11, 15], 9) == (0, 1)",
      "assert module['two_sum']([3, 2, 4], 6) == (1, 2)",
      "assert module['two_sum']([1, 2], 99) is None"]),

    ("sliding-window-max", "sliding_max",
     "Write sliding_max(values, size) that returns the list of maxima of every contiguous window of the "
     "given size. Return [] when size is larger than the list or not positive.",
     "def sliding_max(values, size):\n"
     "    if size <= 0 or size > len(values):\n"
     "        return []\n"
     "    return [max(values[i:i + size]) for i in range(len(values) - size + 1)]",
     ["assert module['sliding_max']([1, 3, -1, -3, 5, 3, 6, 7], 3) == [3, 3, 5, 5, 6, 7]",
      "assert module['sliding_max']([1, 2], 5) == []",
      "assert module['sliding_max']([4], 1) == [4]"]),

    ("topological-order", "topological_order",
     "Write topological_order(graph) that returns a topological ordering of a dict mapping node -> list "
     "of successors. Break ties by taking the smallest available node first. Return None when the graph "
     "has a cycle.",
     "def topological_order(graph):\n"
     "    indegree = {node: 0 for node in graph}\n"
     "    for node in graph:\n"
     "        for successor in graph[node]:\n"
     "            indegree.setdefault(successor, 0)\n"
     "            indegree[successor] += 1\n"
     "    ready = sorted(node for node, count in indegree.items() if count == 0)\n"
     "    out = []\n"
     "    while ready:\n"
     "        node = ready.pop(0)\n"
     "        out.append(node)\n"
     "        for successor in graph.get(node, []):\n"
     "            indegree[successor] -= 1\n"
     "            if indegree[successor] == 0:\n"
     "                ready.append(successor)\n"
     "        ready.sort()\n"
     "    return out if len(out) == len(indegree) else None",
     ["assert module['topological_order']({'a': ['b'], 'b': ['c'], 'c': []}) == ['a', 'b', 'c']",
      "assert module['topological_order']({'a': ['b'], 'b': ['a']}) is None",
      "assert module['topological_order']({}) == []"]),

    ("has-cycle", "has_cycle",
     "Write has_cycle(graph) that returns True when a directed graph given as a dict node -> list of "
     "successors contains a cycle.",
     "def has_cycle(graph):\n"
     "    state = {}\n"
     "    def visit(node):\n"
     "        if state.get(node) == 1:\n"
     "            return True\n"
     "        if state.get(node) == 2:\n"
     "            return False\n"
     "        state[node] = 1\n"
     "        for successor in graph.get(node, []):\n"
     "            if visit(successor):\n"
     "                return True\n"
     "        state[node] = 2\n"
     "        return False\n"
     "    return any(visit(node) for node in list(graph))",
     ["assert module['has_cycle']({'a': ['b'], 'b': ['c'], 'c': ['a']}) is True",
      "assert module['has_cycle']({'a': ['b'], 'b': []}) is False",
      "assert module['has_cycle']({}) is False"]),

    ("shortest-path-unweighted", "shortest_hops",
     "Write shortest_hops(graph, start, goal) that returns the number of edges on a shortest path in an "
     "undirected graph given as a dict node -> list of neighbours. Return -1 when the goal is "
     "unreachable, and 0 when start equals goal.",
     "def shortest_hops(graph, start, goal):\n"
     "    if start == goal:\n"
     "        return 0\n"
     "    seen = {start}\n"
     "    frontier = [start]\n"
     "    distance = 0\n"
     "    while frontier:\n"
     "        distance += 1\n"
     "        nxt = []\n"
     "        for node in frontier:\n"
     "            for neighbour in graph.get(node, []):\n"
     "                if neighbour == goal:\n"
     "                    return distance\n"
     "                if neighbour not in seen:\n"
     "                    seen.add(neighbour)\n"
     "                    nxt.append(neighbour)\n"
     "        frontier = nxt\n"
     "    return -1",
     ["assert module['shortest_hops']({'a': ['b'], 'b': ['c'], 'c': []}, 'a', 'c') == 2",
      "assert module['shortest_hops']({'a': [], 'b': []}, 'a', 'b') == -1",
      "assert module['shortest_hops']({'a': []}, 'a', 'a') == 0"]),

    ("flood-fill-count", "flood_fill_count",
     "Write flood_fill_count(grid, row, col) that returns how many cells are reached by a 4-directional "
     "flood fill starting at (row, col), moving only across cells equal to the starting cell's value. "
     "Return 0 when the coordinates are outside the grid.",
     "def flood_fill_count(grid, row, col):\n"
     "    if not grid or row < 0 or col < 0 or row >= len(grid) or col >= len(grid[0]):\n"
     "        return 0\n"
     "    target = grid[row][col]\n"
     "    seen = set()\n"
     "    stack = [(row, col)]\n"
     "    while stack:\n"
     "        r, c = stack.pop()\n"
     "        if (r, c) in seen:\n"
     "            continue\n"
     "        if r < 0 or c < 0 or r >= len(grid) or c >= len(grid[0]):\n"
     "            continue\n"
     "        if grid[r][c] != target:\n"
     "            continue\n"
     "        seen.add((r, c))\n"
     "        stack += [(r + 1, c), (r - 1, c), (r, c + 1), (r, c - 1)]\n"
     "    return len(seen)",
     ["assert module['flood_fill_count']([[1, 1, 0], [1, 0, 0]], 0, 0) == 3",
      "assert module['flood_fill_count']([[1]], 5, 5) == 0",
      "assert module['flood_fill_count']([[0, 0], [0, 0]], 1, 1) == 4"]),

    ("count-islands", "count_islands",
     "Write count_islands(grid) that counts the groups of 1s connected 4-directionally in a grid of 0s "
     "and 1s.",
     "def count_islands(grid):\n"
     "    if not grid:\n"
     "        return 0\n"
     "    seen = set()\n"
     "    total = 0\n"
     "    for row in range(len(grid)):\n"
     "        for col in range(len(grid[0])):\n"
     "            if grid[row][col] != 1 or (row, col) in seen:\n"
     "                continue\n"
     "            total += 1\n"
     "            stack = [(row, col)]\n"
     "            while stack:\n"
     "                r, c = stack.pop()\n"
     "                if (r, c) in seen:\n"
     "                    continue\n"
     "                if r < 0 or c < 0 or r >= len(grid) or c >= len(grid[0]) or grid[r][c] != 1:\n"
     "                    continue\n"
     "                seen.add((r, c))\n"
     "                stack += [(r + 1, c), (r - 1, c), (r, c + 1), (r, c - 1)]\n"
     "    return total",
     ["assert module['count_islands']([[1, 0], [0, 1]]) == 2",
      "assert module['count_islands']([[1, 1], [1, 1]]) == 1",
      "assert module['count_islands']([]) == 0"]),

    ("spiral-order", "spiral_order",
     "Write spiral_order(matrix) that returns the elements of a rectangular matrix read clockwise from "
     "the top-left corner, as a flat list.",
     "def spiral_order(matrix):\n"
     "    out = []\n"
     "    rows = [list(row) for row in matrix]\n"
     "    while rows:\n"
     "        out += rows.pop(0)\n"
     "        rows = [list(row) for row in zip(*rows)][::-1]\n"
     "    return out",
     ["assert module['spiral_order']([[1, 2], [3, 4]]) == [1, 2, 4, 3]",
      "assert module['spiral_order']([[1, 2, 3], [4, 5, 6], [7, 8, 9]]) == [1, 2, 3, 6, 9, 8, 7, 4, 5]",
      "assert module['spiral_order']([]) == []"]),

    ("rotate-matrix", "rotate_matrix",
     "Write rotate_matrix(matrix) that returns a new square matrix rotated 90 degrees clockwise.",
     "def rotate_matrix(matrix):\n"
     "    return [list(row) for row in zip(*matrix[::-1])]",
     ["assert module['rotate_matrix']([[1, 2], [3, 4]]) == [[3, 1], [4, 2]]",
      "assert module['rotate_matrix']([[1]]) == [[1]]",
      "assert module['rotate_matrix']([]) == []"]),

    ("eval-rpn", "eval_rpn",
     "Write eval_rpn(tokens) that evaluates a list of reverse-Polish tokens using +, -, * and / with "
     "integer truncation toward zero, and returns an int. Raise ValueError on a malformed expression.",
     "def eval_rpn(tokens):\n"
     "    stack = []\n"
     "    for token in tokens:\n"
     "        if token in ('+', '-', '*', '/'):\n"
     "            if len(stack) < 2:\n"
     "                raise ValueError('malformed expression')\n"
     "            b = stack.pop()\n"
     "            a = stack.pop()\n"
     "            if token == '+':\n"
     "                stack.append(a + b)\n"
     "            elif token == '-':\n"
     "                stack.append(a - b)\n"
     "            elif token == '*':\n"
     "                stack.append(a * b)\n"
     "            else:\n"
     "                stack.append(int(a / b))\n"
     "        else:\n"
     "            stack.append(int(token))\n"
     "    if len(stack) != 1:\n"
     "        raise ValueError('malformed expression')\n"
     "    return stack[0]",
     ["assert module['eval_rpn'](['2', '3', '+']) == 5",
      "assert module['eval_rpn'](['4', '13', '5', '/', '+']) == 6",
      "try:\n    module['eval_rpn'](['+'])\n    raise AssertionError('should raise')\nexcept ValueError:\n    pass"]),

    ("balanced-with-pairs", "balanced_pairs",
     "Write balanced_pairs(text) that returns True when (), [] and {} are correctly nested and matched "
     "in text, ignoring every other character.",
     "def balanced_pairs(text):\n"
     "    pairs = {')': '(', ']': '[', '}': '{'}\n"
     "    stack = []\n"
     "    for char in text:\n"
     "        if char in '([{':\n"
     "            stack.append(char)\n"
     "        elif char in pairs:\n"
     "            if not stack or stack.pop() != pairs[char]:\n"
     "                return False\n"
     "    return not stack",
     ["assert module['balanced_pairs']('a(b[c]{d})') is True",
      "assert module['balanced_pairs']('([)]') is False",
      "assert module['balanced_pairs']('') is True"]),

    ("base-convert", "base_convert",
     "Write base_convert(number, base) that renders a non-negative int in the given base from 2 to 36, "
     "using lowercase digits, without importing any module. Zero renders as '0'.",
     "def base_convert(number, base):\n"
     "    if base < 2 or base > 36:\n"
     "        raise ValueError('base out of range')\n"
     "    if number == 0:\n"
     "        return '0'\n"
     "    digits = '0123456789abcdefghijklmnopqrstuvwxyz'\n"
     "    out = []\n"
     "    while number:\n"
     "        out.append(digits[number % base])\n"
     "        number //= base\n"
     "    return ''.join(reversed(out))",
     ["assert module['base_convert'](255, 16) == 'ff'",
      "assert module['base_convert'](0, 2) == '0'",
      "assert module['base_convert'](35, 36) == 'z'"]),

    ("from-base", "from_base",
     "Write from_base(text, base) that parses a lowercase string in the given base from 2 to 36 into an "
     "int, without importing any module. Raise ValueError on an invalid digit or empty text.",
     "def from_base(text, base):\n"
     "    digits = '0123456789abcdefghijklmnopqrstuvwxyz'[:base]\n"
     "    if not text:\n"
     "        raise ValueError('empty')\n"
     "    total = 0\n"
     "    for char in text:\n"
     "        if char not in digits:\n"
     "            raise ValueError('invalid digit')\n"
     "        total = total * base + digits.index(char)\n"
     "    return total",
     ["assert module['from_base']('ff', 16) == 255",
      "assert module['from_base']('1010', 2) == 10",
      "try:\n    module['from_base']('2', 2)\n    raise AssertionError('should raise')\nexcept ValueError:\n    pass"]),

    ("sieve-primes", "primes_below",
     "Write primes_below(limit) that returns the sorted list of primes strictly below limit, using a "
     "sieve. Return [] when limit is 2 or less.",
     "def primes_below(limit):\n"
     "    if limit <= 2:\n"
     "        return []\n"
     "    flags = [True] * limit\n"
     "    flags[0] = flags[1] = False\n"
     "    step = 2\n"
     "    while step * step < limit:\n"
     "        if flags[step]:\n"
     "            for multiple in range(step * step, limit, step):\n"
     "                flags[multiple] = False\n"
     "        step += 1\n"
     "    return [i for i, ok in enumerate(flags) if ok]",
     ["assert module['primes_below'](10) == [2, 3, 5, 7]",
      "assert module['primes_below'](2) == []",
      "assert module['primes_below'](3) == [2]"]),

    ("modular-power", "mod_pow",
     "Write mod_pow(base, exponent, modulus) that computes (base ** exponent) % modulus by repeated "
     "squaring, without using the three-argument pow. The exponent is non-negative.",
     "def mod_pow(base, exponent, modulus):\n"
     "    result = 1 % modulus\n"
     "    base %= modulus\n"
     "    while exponent:\n"
     "        if exponent & 1:\n"
     "            result = (result * base) % modulus\n"
     "        base = (base * base) % modulus\n"
     "        exponent >>= 1\n"
     "    return result",
     ["assert module['mod_pow'](2, 10, 1000) == 24",
      "assert module['mod_pow'](5, 0, 7) == 1",
      "assert module['mod_pow'](3, 200, 50) == pow(3, 200, 50)"]),

    ("collatz-length", "collatz_length",
     "Write collatz_length(n) that returns the number of steps to reach 1 from a positive integer n "
     "using the Collatz rule (halve when even, otherwise 3n+1). collatz_length(1) is 0.",
     "def collatz_length(n):\n"
     "    steps = 0\n"
     "    while n != 1:\n"
     "        n = n // 2 if n % 2 == 0 else 3 * n + 1\n"
     "        steps += 1\n"
     "    return steps",
     ["assert module['collatz_length'](1) == 0",
      "assert module['collatz_length'](6) == 8",
      "assert module['collatz_length'](27) == 111"]),

    ("coin-change-min", "coin_change",
     "Write coin_change(coins, amount) that returns the fewest coins summing exactly to amount, or -1 "
     "when it cannot be made. coin_change(anything, 0) is 0.",
     "def coin_change(coins, amount):\n"
     "    best = [0] + [amount + 1] * amount\n"
     "    for value in range(1, amount + 1):\n"
     "        for coin in coins:\n"
     "            if coin <= value:\n"
     "                best[value] = min(best[value], best[value - coin] + 1)\n"
     "    return -1 if best[amount] > amount else best[amount]",
     ["assert module['coin_change']([1, 5, 10], 12) == 3",
      "assert module['coin_change']([2], 3) == -1",
      "assert module['coin_change']([5], 0) == 0"]),

    ("binary-search-leftmost", "search_leftmost",
     "Write search_leftmost(values, target) that returns the index of the first occurrence of target in "
     "an ascending list, or -1 when absent. Use binary search, not list.index.",
     "def search_leftmost(values, target):\n"
     "    low, high = 0, len(values)\n"
     "    while low < high:\n"
     "        mid = (low + high) // 2\n"
     "        if values[mid] < target:\n"
     "            low = mid + 1\n"
     "        else:\n"
     "            high = mid\n"
     "    return low if low < len(values) and values[low] == target else -1",
     ["assert module['search_leftmost']([1, 2, 2, 2, 3], 2) == 1",
      "assert module['search_leftmost']([1, 3], 2) == -1",
      "assert module['search_leftmost']([], 1) == -1"]),

    ("kth-smallest", "kth_smallest",
     "Write kth_smallest(values, k) that returns the k-th smallest element of a list, counting from 1. "
     "Raise ValueError when k is out of range.",
     "def kth_smallest(values, k):\n"
     "    if k < 1 or k > len(values):\n"
     "        raise ValueError('k out of range')\n"
     "    return sorted(values)[k - 1]",
     ["assert module['kth_smallest']([5, 1, 3], 2) == 3",
      "assert module['kth_smallest']([2], 1) == 2",
      "try:\n    module['kth_smallest']([1], 5)\n    raise AssertionError('should raise')\nexcept ValueError:\n    pass"]),
]

_TEXT_AND_DATA: list[tuple[str, str, str, str, list[str]]] = [
    ("word-wrap", "word_wrap",
     "Write word_wrap(text, width) that greedily wraps text into lines of at most width characters, "
     "breaking only between words separated by whitespace. A word longer than width goes on its own "
     "line unbroken. Return [] for text with no words.",
     "def word_wrap(text, width):\n"
     "    lines = []\n"
     "    current = ''\n"
     "    for word in text.split():\n"
     "        if not current:\n"
     "            current = word\n"
     "        elif len(current) + 1 + len(word) <= width:\n"
     "            current += ' ' + word\n"
     "        else:\n"
     "            lines.append(current)\n"
     "            current = word\n"
     "    if current:\n"
     "        lines.append(current)\n"
     "    return lines",
     ["assert module['word_wrap']('the quick brown fox', 10) == ['the quick', 'brown fox']",
      "assert module['word_wrap']('', 5) == []",
      "assert module['word_wrap']('supercalifragilistic', 5) == ['supercalifragilistic']"]),

    ("snake-to-camel", "snake_to_camel",
     "Write snake_to_camel(name) that converts snake_case to lowerCamelCase, so 'user_id_value' "
     "becomes 'userIdValue'. Leading, trailing and repeated underscores are ignored.",
     "def snake_to_camel(name):\n"
     "    parts = [p for p in name.split('_') if p]\n"
     "    if not parts:\n"
     "        return ''\n"
     "    return parts[0].lower() + ''.join(p[:1].upper() + p[1:].lower() for p in parts[1:])",
     ["assert module['snake_to_camel']('user_id_value') == 'userIdValue'",
      "assert module['snake_to_camel']('__a__b__') == 'aB'",
      "assert module['snake_to_camel']('') == ''"]),

    ("camel-to-snake", "camel_to_snake",
     "Write camel_to_snake(name) that converts CamelCase or lowerCamelCase to snake_case, so "
     "'HTTPServerError' becomes 'http_server_error'. Do not import any module.",
     "def camel_to_snake(name):\n"
     "    out = []\n"
     "    for index, char in enumerate(name):\n"
     "        if char.isupper():\n"
     "            previous_lower = index > 0 and not name[index - 1].isupper()\n"
     "            next_lower = index + 1 < len(name) and name[index + 1].islower()\n"
     "            if index and (previous_lower or next_lower):\n"
     "                out.append('_')\n"
     "            out.append(char.lower())\n"
     "        else:\n"
     "            out.append(char)\n"
     "    return ''.join(out)",
     ["assert module['camel_to_snake']('HTTPServerError') == 'http_server_error'",
      "assert module['camel_to_snake']('userId') == 'user_id'",
      "assert module['camel_to_snake']('') == ''"]),

    ("anagram-groups", "anagram_groups",
     "Write anagram_groups(words) that groups words that are anagrams of each other. Return a list of "
     "groups, each group sorted alphabetically, and the groups sorted by their first word.",
     "def anagram_groups(words):\n"
     "    buckets = {}\n"
     "    for word in words:\n"
     "        buckets.setdefault(''.join(sorted(word)), []).append(word)\n"
     "    groups = [sorted(group) for group in buckets.values()]\n"
     "    return sorted(groups, key=lambda g: g[0])",
     ["assert module['anagram_groups'](['eat', 'tea', 'tan', 'ate']) == [['ate', 'eat', 'tea'], ['tan']]",
      "assert module['anagram_groups']([]) == []",
      "assert module['anagram_groups'](['a']) == [['a']]"]),

    ("template-render", "render_template",
     "Write render_template(template, values) that replaces every {name} placeholder with the matching "
     "value from the dict, converted with str. A placeholder with no matching key is left as-is. "
     "Do not import any module and do not use str.format.",
     "def render_template(template, values):\n"
     "    out = []\n"
     "    index = 0\n"
     "    while index < len(template):\n"
     "        char = template[index]\n"
     "        if char == '{' and '}' in template[index:]:\n"
     "            end = template.index('}', index)\n"
     "            name = template[index + 1:end]\n"
     "            if name in values:\n"
     "                out.append(str(values[name]))\n"
     "            else:\n"
     "                out.append(template[index:end + 1])\n"
     "            index = end + 1\n"
     "            continue\n"
     "        out.append(char)\n"
     "        index += 1\n"
     "    return ''.join(out)",
     ["assert module['render_template']('hi {name}', {'name': 'vic'}) == 'hi vic'",
      "assert module['render_template']('{a}{b}', {'a': 1, 'b': 2}) == '12'",
      "assert module['render_template']('{missing}', {}) == '{missing}'"]),

    ("longest-common-prefix", "common_prefix",
     "Write common_prefix(words) that returns the longest string that starts every word in the list. "
     "Return '' for an empty list or when there is no shared prefix.",
     "def common_prefix(words):\n"
     "    if not words:\n"
     "        return ''\n"
     "    shortest = min(words, key=len)\n"
     "    for index, char in enumerate(shortest):\n"
     "        if any(word[index] != char for word in words):\n"
     "            return shortest[:index]\n"
     "    return shortest",
     ["assert module['common_prefix'](['flower', 'flow', 'flight']) == 'fl'",
      "assert module['common_prefix'](['a', 'b']) == ''",
      "assert module['common_prefix']([]) == ''"]),

    ("deep-merge", "deep_merge",
     "Write deep_merge(base, override) that merges two nested dicts recursively and returns a new dict. "
     "When both sides hold a dict for the same key the dicts merge; otherwise the override value wins. "
     "Neither input is modified.",
     "def deep_merge(base, override):\n"
     "    out = dict(base)\n"
     "    for key, value in override.items():\n"
     "        if key in out and isinstance(out[key], dict) and isinstance(value, dict):\n"
     "            out[key] = deep_merge(out[key], value)\n"
     "        else:\n"
     "            out[key] = value\n"
     "    return out",
     ["assert module['deep_merge']({'a': {'x': 1}}, {'a': {'y': 2}}) == {'a': {'x': 1, 'y': 2}}",
      "assert module['deep_merge']({'a': 1}, {'a': 2}) == {'a': 2}",
      "base = {'a': {'x': 1}}\nmodule['deep_merge'](base, {'a': {'x': 9}})\nassert base == {'a': {'x': 1}}"]),

    ("flatten-keys", "flatten_keys",
     "Write flatten_keys(data) that flattens a nested dict into a single level where keys are joined "
     "with '.', so {'a': {'b': 1}} becomes {'a.b': 1}. Empty dicts disappear.",
     "def flatten_keys(data):\n"
     "    out = {}\n"
     "    def walk(node, prefix):\n"
     "        for key, value in node.items():\n"
     "            path = f'{prefix}.{key}' if prefix else str(key)\n"
     "            if isinstance(value, dict):\n"
     "                walk(value, path)\n"
     "            else:\n"
     "                out[path] = value\n"
     "    walk(data, '')\n"
     "    return out",
     ["assert module['flatten_keys']({'a': {'b': 1}, 'c': 2}) == {'a.b': 1, 'c': 2}",
      "assert module['flatten_keys']({}) == {}",
      "assert module['flatten_keys']({'a': {}}) == {}"]),

    ("unflatten-keys", "unflatten_keys",
     "Write unflatten_keys(data) that rebuilds a nested dict from dotted keys, so {'a.b': 1} becomes "
     "{'a': {'b': 1}}.",
     "def unflatten_keys(data):\n"
     "    out = {}\n"
     "    for path, value in data.items():\n"
     "        parts = path.split('.')\n"
     "        node = out\n"
     "        for part in parts[:-1]:\n"
     "            node = node.setdefault(part, {})\n"
     "        node[parts[-1]] = value\n"
     "    return out",
     ["assert module['unflatten_keys']({'a.b': 1, 'c': 2}) == {'a': {'b': 1}, 'c': 2}",
      "assert module['unflatten_keys']({}) == {}",
      "assert module['unflatten_keys']({'x.y.z': 3}) == {'x': {'y': {'z': 3}}}"]),

    ("group-by-key", "group_by_key",
     "Write group_by_key(rows, key) that groups a list of dicts by the value of the given key and "
     "returns a dict value -> list of rows, preserving input order. Rows lacking the key are skipped.",
     "def group_by_key(rows, key):\n"
     "    out = {}\n"
     "    for row in rows:\n"
     "        if key not in row:\n"
     "            continue\n"
     "        out.setdefault(row[key], []).append(row)\n"
     "    return out",
     ["assert module['group_by_key']([{'k': 'a'}, {'k': 'b'}, {'k': 'a'}], 'k') == "
      "{'a': [{'k': 'a'}, {'k': 'a'}], 'b': [{'k': 'b'}]}",
      "assert module['group_by_key']([{'x': 1}], 'k') == {}",
      "assert module['group_by_key']([], 'k') == {}"]),

    ("sort-by-multiple", "sort_by_multiple",
     "Write sort_by_multiple(rows, keys) that sorts a list of dicts by several keys in order. A key "
     "prefixed with '-' sorts descending. Assume every row holds every key and the values compare.",
     "def sort_by_multiple(rows, keys):\n"
     "    out = list(rows)\n"
     "    for key in reversed(keys):\n"
     "        descending = key.startswith('-')\n"
     "        name = key[1:] if descending else key\n"
     "        out.sort(key=lambda row: row[name], reverse=descending)\n"
     "    return out",
     ["assert module['sort_by_multiple']([{'a': 2}, {'a': 1}], ['a']) == [{'a': 1}, {'a': 2}]",
      "assert module['sort_by_multiple']([{'a': 1}, {'a': 2}], ['-a']) == [{'a': 2}, {'a': 1}]",
      "rows = [{'a': 1, 'b': 2}, {'a': 1, 'b': 1}]\n"
      "assert module['sort_by_multiple'](rows, ['a', 'b']) == [{'a': 1, 'b': 1}, {'a': 1, 'b': 2}]"]),

    ("top-k-frequent", "top_k_frequent",
     "Write top_k_frequent(items, k) that returns the k most frequent items, most frequent first, "
     "breaking ties by first appearance in the input.",
     "def top_k_frequent(items, k):\n"
     "    counts = {}\n"
     "    order = {}\n"
     "    for index, item in enumerate(items):\n"
     "        counts[item] = counts.get(item, 0) + 1\n"
     "        order.setdefault(item, index)\n"
     "    ranked = sorted(counts, key=lambda item: (-counts[item], order[item]))\n"
     "    return ranked[:k]",
     ["assert module['top_k_frequent'](['a', 'b', 'a', 'c', 'b', 'a'], 2) == ['a', 'b']",
      "assert module['top_k_frequent'](['x', 'y'], 5) == ['x', 'y']",
      "assert module['top_k_frequent']([], 3) == []"]),

    ("lru-survivors", "lru_survivors",
     "Write lru_survivors(keys, capacity) that replays a sequence of key accesses through an LRU cache "
     "of the given capacity and returns the keys still cached, most recently used first.",
     "def lru_survivors(keys, capacity):\n"
     "    cache = []\n"
     "    for key in keys:\n"
     "        if key in cache:\n"
     "            cache.remove(key)\n"
     "        cache.insert(0, key)\n"
     "        if len(cache) > capacity:\n"
     "            cache.pop()\n"
     "    return cache",
     ["assert module['lru_survivors'](['a', 'b', 'c', 'a'], 2) == ['a', 'c']",
      "assert module['lru_survivors']([], 3) == []",
      "assert module['lru_survivors'](['x', 'x', 'x'], 1) == ['x']"]),

    ("chunk-by-size", "chunk_bytes",
     "Write chunk_bytes(items, limit) that splits a list of (name, size) pairs into consecutive groups "
     "whose sizes sum to at most limit, starting a new group when adding an item would exceed it. "
     "An item larger than limit sits alone in its own group.",
     "def chunk_bytes(items, limit):\n"
     "    groups = []\n"
     "    current = []\n"
     "    total = 0\n"
     "    for name, size in items:\n"
     "        if current and total + size > limit:\n"
     "            groups.append(current)\n"
     "            current = []\n"
     "            total = 0\n"
     "        current.append((name, size))\n"
     "        total += size\n"
     "    if current:\n"
     "        groups.append(current)\n"
     "    return groups",
     ["assert module['chunk_bytes']([('a', 3), ('b', 4), ('c', 2)], 6) == [[('a', 3)], [('b', 4), ('c', 2)]]",
      "assert module['chunk_bytes']([], 10) == []",
      "assert module['chunk_bytes']([('big', 99)], 10) == [[('big', 99)]]"]),

    ("diff-added-removed", "diff_lines",
     "Write diff_lines(before, after) that compares two lists of lines and returns the pair "
     "(added, removed): lines present only in after, and lines present only in before, each keeping "
     "its original order and without duplicates.",
     "def diff_lines(before, after):\n"
     "    before_set = set(before)\n"
     "    after_set = set(after)\n"
     "    added = []\n"
     "    for line in after:\n"
     "        if line not in before_set and line not in added:\n"
     "            added.append(line)\n"
     "    removed = []\n"
     "    for line in before:\n"
     "        if line not in after_set and line not in removed:\n"
     "            removed.append(line)\n"
     "    return (added, removed)",
     ["assert module['diff_lines'](['a', 'b'], ['b', 'c']) == (['c'], ['a'])",
      "assert module['diff_lines']([], []) == ([], [])",
      "assert module['diff_lines'](['x', 'x'], []) == ([], ['x'])"]),

    ("normalize-path", "normalize_path",
     "Write normalize_path(path) that resolves '.' and '..' in a POSIX absolute path and returns the "
     "shortest equivalent path, always starting with '/' and never ending with '/' unless it is root. "
     "Do not import any module.",
     "def normalize_path(path):\n"
     "    stack = []\n"
     "    for part in path.split('/'):\n"
     "        if not part or part == '.':\n"
     "            continue\n"
     "        if part == '..':\n"
     "            if stack:\n"
     "                stack.pop()\n"
     "            continue\n"
     "        stack.append(part)\n"
     "    return '/' + '/'.join(stack)",
     ["assert module['normalize_path']('/a/./b/../c/') == '/a/c'",
      "assert module['normalize_path']('/../') == '/'",
      "assert module['normalize_path']('/a//b') == '/a/b'"]),

    ("relative-path", "relative_path",
     "Write relative_path(source, target) that returns the relative POSIX path from one absolute "
     "directory to another, using '..' to climb. Return '.' when they are the same.",
     "def relative_path(source, target):\n"
     "    a = [p for p in source.split('/') if p]\n"
     "    b = [p for p in target.split('/') if p]\n"
     "    common = 0\n"
     "    while common < len(a) and common < len(b) and a[common] == b[common]:\n"
     "        common += 1\n"
     "    parts = ['..'] * (len(a) - common) + b[common:]\n"
     "    return '/'.join(parts) if parts else '.'",
     ["assert module['relative_path']('/a/b', '/a/c') == '../c'",
      "assert module['relative_path']('/a', '/a') == '.'",
      "assert module['relative_path']('/a/b/c', '/a') == '../..'"]),

    ("count-log-window", "busiest_minute",
     "Write busiest_minute(minutes) that returns the minute value appearing most often in a list of "
     "ints, breaking ties by the smallest minute. Return None for an empty list.",
     "def busiest_minute(minutes):\n"
     "    if not minutes:\n"
     "        return None\n"
     "    counts = {}\n"
     "    for minute in minutes:\n"
     "        counts[minute] = counts.get(minute, 0) + 1\n"
     "    return min(counts, key=lambda m: (-counts[m], m))",
     ["assert module['busiest_minute']([1, 2, 2, 3]) == 2",
      "assert module['busiest_minute']([4, 1]) == 1",
      "assert module['busiest_minute']([]) is None"]),

    ("days-in-month", "days_in_month",
     "Write days_in_month(year, month) that returns the number of days, handling leap years by the "
     "Gregorian rule. Raise ValueError when month is outside 1..12. Do not import any module.",
     "def days_in_month(year, month):\n"
     "    if month < 1 or month > 12:\n"
     "        raise ValueError('bad month')\n"
     "    if month == 2:\n"
     "        leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)\n"
     "        return 29 if leap else 28\n"
     "    return 30 if month in (4, 6, 9, 11) else 31",
     ["assert module['days_in_month'](2024, 2) == 29",
      "assert module['days_in_month'](1900, 2) == 28",
      "try:\n    module['days_in_month'](2024, 13)\n    raise AssertionError('should raise')\nexcept ValueError:\n    pass"]),

    ("day-of-year", "day_of_year",
     "Write day_of_year(year, month, day) that returns the 1-based ordinal day within the year, "
     "handling leap years. Do not import any module.",
     "def day_of_year(year, month, day):\n"
     "    leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)\n"
     "    lengths = [31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]\n"
     "    return sum(lengths[:month - 1]) + day",
     ["assert module['day_of_year'](2024, 3, 1) == 61",
      "assert module['day_of_year'](2023, 1, 1) == 1",
      "assert module['day_of_year'](2023, 12, 31) == 365"]),

    ("seconds-to-clock", "seconds_to_clock",
     "Write seconds_to_clock(total) that formats a non-negative number of seconds as 'H:MM:SS' with no "
     "leading zero on the hours.",
     "def seconds_to_clock(total):\n"
     "    hours, rest = divmod(total, 3600)\n"
     "    minutes, seconds = divmod(rest, 60)\n"
     "    return f'{hours}:{minutes:02d}:{seconds:02d}'",
     ["assert module['seconds_to_clock'](3661) == '1:01:01'",
      "assert module['seconds_to_clock'](0) == '0:00:00'",
      "assert module['seconds_to_clock'](59) == '0:00:59'"]),

    ("weighted-average", "weighted_average",
     "Write weighted_average(pairs) that returns the weighted mean of (value, weight) pairs as a float. "
     "Raise ValueError when the list is empty or the weights sum to zero.",
     "def weighted_average(pairs):\n"
     "    total_weight = sum(weight for _, weight in pairs)\n"
     "    if not pairs or total_weight == 0:\n"
     "        raise ValueError('no weight')\n"
     "    return sum(value * weight for value, weight in pairs) / total_weight",
     ["assert module['weighted_average']([(10, 1), (20, 3)]) == 17.5",
      "assert module['weighted_average']([(5, 2)]) == 5.0",
      "try:\n    module['weighted_average']([])\n    raise AssertionError('should raise')\nexcept ValueError:\n    pass"]),

    ("percentile-nearest", "percentile",
     "Write percentile(values, fraction) that returns the value at the given fraction (0..1) of a list "
     "using nearest-rank on the sorted values. Raise ValueError on an empty list or a fraction outside "
     "0..1.",
     "def percentile(values, fraction):\n"
     "    if not values or fraction < 0 or fraction > 1:\n"
     "        raise ValueError('bad input')\n"
     "    ordered = sorted(values)\n"
     "    rank = max(1, int(round(fraction * len(ordered))))\n"
     "    rank = min(rank, len(ordered))\n"
     "    return ordered[rank - 1]",
     ["assert module['percentile']([1, 2, 3, 4], 0.5) == 2",
      "assert module['percentile']([1, 2, 3, 4], 1) == 4",
      "try:\n    module['percentile']([], 0.5)\n    raise AssertionError('should raise')\nexcept ValueError:\n    pass"]),

    ("stddev-population", "stddev",
     "Write stddev(values) that returns the population standard deviation of a non-empty list of "
     "numbers as a float, without importing any module.",
     "def stddev(values):\n"
     "    mean = sum(values) / len(values)\n"
     "    variance = sum((value - mean) ** 2 for value in values) / len(values)\n"
     "    return variance ** 0.5",
     ["assert abs(module['stddev']([2, 4, 4, 4, 5, 5, 7, 9]) - 2.0) < 1e-9",
      "assert module['stddev']([3]) == 0.0",
      "assert abs(module['stddev']([1, 3]) - 1.0) < 1e-9"]),

    ("histogram-buckets", "histogram",
     "Write histogram(values, size) that counts values into consecutive buckets of the given positive "
     "size starting at zero, and returns a dict bucket_start -> count. Only non-empty buckets appear.",
     "def histogram(values, size):\n"
     "    if size <= 0:\n"
     "        raise ValueError('size must be positive')\n"
     "    out = {}\n"
     "    for value in values:\n"
     "        start = (value // size) * size\n"
     "        out[start] = out.get(start, 0) + 1\n"
     "    return out",
     ["assert module['histogram']([1, 2, 11], 10) == {0: 2, 10: 1}",
      "assert module['histogram']([], 5) == {}",
      "try:\n    module['histogram']([1], 0)\n    raise AssertionError('should raise')\nexcept ValueError:\n    pass"]),
]

HARDER_TASKS: list[tuple[str, str, str, str, list[str]]] = _PARSING + _NETWORK + _ALGORITHMS + _TEXT_AND_DATA
