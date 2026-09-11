#!/usr/bin/env python3
"""Generate the arena PRACTICE task suite (distinct from the sealed 50-task benchmark).

Each task carries a reference solution used only to self-validate the task here;
the emitted suite contains just id/function_name/prompt/test_source, exactly what
the arena and the CORE-increment bridge consume.  Domains match the project:
text, numbers, data structures, parsing, networking and sysadmin — all pure,
offline, deterministic Python (no network, no clock, no host paths).

Run:  python3 -B tools/generate_arena_practice_suite.py --out configs/arena/practice-suite.v1.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Callable

SUITE_SCHEMA = "arena-practice-suite.v1"

# (slug, function_name, prompt, reference_solution, [assert lines using module[fn]])
TASKS: list[tuple[str, str, str, str, list[str]]] = [
    # --- text ---------------------------------------------------------------
    ("reverse-words", "reverse_words", "Write reverse_words(s) that returns the words of s in reverse order, single-spaced.",
     "def reverse_words(s):\n    return ' '.join(s.split()[::-1])",
     ["assert module['reverse_words']('a b c') == 'c b a'", "assert module['reverse_words']('  hi   there ') == 'there hi'", "assert module['reverse_words']('') == ''"]),
    ("count-vowels", "count_vowels", "Write count_vowels(s) that returns the number of vowels (aeiou, case-insensitive) in s.",
     "def count_vowels(s):\n    return sum(c.lower() in 'aeiou' for c in s)",
     ["assert module['count_vowels']('Hello') == 2", "assert module['count_vowels']('xyz') == 0", "assert module['count_vowels']('AEIOU') == 5"]),
    ("is-palindrome", "is_palindrome", "Write is_palindrome(s) that returns True if s reads the same forwards and backwards, ignoring case and spaces.",
     "def is_palindrome(s):\n    t = ''.join(s.lower().split())\n    return t == t[::-1]",
     ["assert module['is_palindrome']('Never odd or even') is True", "assert module['is_palindrome']('hello') is False", "assert module['is_palindrome']('') is True"]),
    ("title-case", "title_case", "Write title_case(s) that capitalises the first letter of each word and lowercases the rest.",
     "def title_case(s):\n    return ' '.join(w[:1].upper() + w[1:].lower() for w in s.split())",
     ["assert module['title_case']('hello WORLD') == 'Hello World'", "assert module['title_case']('a') == 'A'", "assert module['title_case']('') == ''"]),
    ("most-common-char", "most_common_char", "Write most_common_char(s) that returns the most frequent character in the non-empty string s; on a tie return the one that appears first.",
     "def most_common_char(s):\n    best = None; best_n = -1\n    for c in s:\n        n = s.count(c)\n        if n > best_n:\n            best, best_n = c, n\n    return best",
     ["assert module['most_common_char']('aabbb') == 'b'", "assert module['most_common_char']('abab') == 'a'", "assert module['most_common_char']('x') == 'x'"]),
    ("run-length", "run_length", "Write run_length(s) that returns the run-length encoding of s as a string, e.g. 'aaab' -> 'a3b1'.",
     "def run_length(s):\n    out = []\n    i = 0\n    while i < len(s):\n        j = i\n        while j < len(s) and s[j] == s[i]:\n            j += 1\n        out.append(s[i] + str(j - i))\n        i = j\n    return ''.join(out)",
     ["assert module['run_length']('aaab') == 'a3b1'", "assert module['run_length']('') == ''", "assert module['run_length']('abc') == 'a1b1c1'"]),
    ("slugify", "slugify", "Write slugify(s) that lowercases s, replaces any run of non-alphanumeric characters with a single hyphen, and strips leading/trailing hyphens.",
     "def slugify(s):\n    out = []\n    prev_dash = False\n    for c in s.lower():\n        if c.isalnum():\n            out.append(c); prev_dash = False\n        elif not prev_dash:\n            out.append('-'); prev_dash = True\n    return ''.join(out).strip('-')",
     ["assert module['slugify']('Hello, World!') == 'hello-world'", "assert module['slugify']('  a__b  ') == 'a-b'", "assert module['slugify']('---') == ''"]),
    ("caesar", "caesar", "Write caesar(s, n) that shifts each lowercase ASCII letter in s forward by n positions (wrapping a-z); leave other characters unchanged.",
     "def caesar(s, n):\n    return ''.join(chr((ord(c) - 97 + n) % 26 + 97) if 'a' <= c <= 'z' else c for c in s)",
     ["assert module['caesar']('abc', 1) == 'bcd'", "assert module['caesar']('xyz', 3) == 'abc'", "assert module['caesar']('a.b', 1) == 'b.c'"]),
    ("word-frequencies", "word_frequencies", "Write word_frequencies(s) that returns a dict mapping each whitespace-separated word to its count.",
     "def word_frequencies(s):\n    d = {}\n    for w in s.split():\n        d[w] = d.get(w, 0) + 1\n    return d",
     ["assert module['word_frequencies']('a b a') == {'a': 2, 'b': 1}", "assert module['word_frequencies']('') == {}"]),
    ("strip-comments", "strip_comments", "Write strip_comments(s) that returns s with everything from the first '#' on each line removed, keeping the newlines.",
     "def strip_comments(s):\n    return '\\n'.join(line.split('#', 1)[0] for line in s.split('\\n'))",
     ["assert module['strip_comments']('a # b') == 'a '", "assert module['strip_comments']('x\\ny # z') == 'x\\ny '", "assert module['strip_comments']('# all') == ''"]),
    # --- numbers ------------------------------------------------------------
    ("fizzbuzz", "fizzbuzz", "Write fizzbuzz(n) that returns a list of strings for 1..n: 'Fizz' for multiples of 3, 'Buzz' for 5, 'FizzBuzz' for both, else the number as a string.",
     "def fizzbuzz(n):\n    out = []\n    for i in range(1, n + 1):\n        if i % 15 == 0: out.append('FizzBuzz')\n        elif i % 3 == 0: out.append('Fizz')\n        elif i % 5 == 0: out.append('Buzz')\n        else: out.append(str(i))\n    return out",
     ["assert module['fizzbuzz'](5) == ['1', '2', 'Fizz', '4', 'Buzz']", "assert module['fizzbuzz'](15)[-1] == 'FizzBuzz'", "assert module['fizzbuzz'](0) == []"]),
    ("gcd", "gcd", "Write gcd(a, b) that returns the greatest common divisor of two non-negative integers, with gcd(0, 0) == 0.",
     "def gcd(a, b):\n    while b:\n        a, b = b, a % b\n    return a",
     ["assert module['gcd'](12, 8) == 4", "assert module['gcd'](0, 5) == 5", "assert module['gcd'](0, 0) == 0"]),
    ("is-prime", "is_prime", "Write is_prime(n) that returns True if the integer n is a prime number, False otherwise.",
     "def is_prime(n):\n    if n < 2: return False\n    i = 2\n    while i * i <= n:\n        if n % i == 0: return False\n        i += 1\n    return True",
     ["assert module['is_prime'](7) is True", "assert module['is_prime'](1) is False", "assert module['is_prime'](9) is False", "assert module['is_prime'](2) is True"]),
    ("prime-factors", "prime_factors", "Write prime_factors(n) that returns the prime factors of an integer n > 1 in ascending order with repeats.",
     "def prime_factors(n):\n    out = []\n    d = 2\n    while d * d <= n:\n        while n % d == 0:\n            out.append(d); n //= d\n        d += 1\n    if n > 1: out.append(n)\n    return out",
     ["assert module['prime_factors'](12) == [2, 2, 3]", "assert module['prime_factors'](7) == [7]", "assert module['prime_factors'](2) == [2]"]),
    ("digit-sum", "digit_sum", "Write digit_sum(n) that returns the sum of the decimal digits of a non-negative integer n.",
     "def digit_sum(n):\n    return sum(int(c) for c in str(n))",
     ["assert module['digit_sum'](123) == 6", "assert module['digit_sum'](0) == 0", "assert module['digit_sum'](99) == 18"]),
    ("to-binary", "to_binary", "Write to_binary(n) that returns the binary representation of a non-negative integer n as a string without a '0b' prefix.",
     "def to_binary(n):\n    return bin(n)[2:]",
     ["assert module['to_binary'](5) == '101'", "assert module['to_binary'](0) == '0'", "assert module['to_binary'](8) == '1000'"]),
    ("clamp", "clamp", "Write clamp(x, lo, hi) that returns x limited to the range [lo, hi].",
     "def clamp(x, lo, hi):\n    return lo if x < lo else hi if x > hi else x",
     ["assert module['clamp'](5, 0, 10) == 5", "assert module['clamp'](-1, 0, 10) == 0", "assert module['clamp'](99, 0, 10) == 10"]),
    ("mean", "mean", "Write mean(values) that returns the arithmetic mean of a non-empty list of numbers as a float.",
     "def mean(values):\n    return sum(values) / len(values)",
     ["assert module['mean']([1, 2, 3]) == 2.0", "assert module['mean']([5]) == 5.0", "assert abs(module['mean']([1, 2]) - 1.5) < 1e-9"]),
    ("median", "median", "Write median(values) that returns the median of a non-empty list of numbers; for an even count return the average of the two middle values.",
     "def median(values):\n    s = sorted(values); n = len(s); m = n // 2\n    return s[m] if n % 2 else (s[m - 1] + s[m]) / 2",
     ["assert module['median']([3, 1, 2]) == 2", "assert module['median']([1, 2, 3, 4]) == 2.5", "assert module['median']([7]) == 7"]),
    ("roman", "roman", "Write roman(n) that converts an integer 1..3999 to its uppercase Roman numeral.",
     "def roman(n):\n    vals = [(1000,'M'),(900,'CM'),(500,'D'),(400,'CD'),(100,'C'),(90,'XC'),(50,'L'),(40,'XL'),(10,'X'),(9,'IX'),(5,'V'),(4,'IV'),(1,'I')]\n    out = []\n    for v, sym in vals:\n        while n >= v:\n            out.append(sym); n -= v\n    return ''.join(out)",
     ["assert module['roman'](4) == 'IV'", "assert module['roman'](2024) == 'MMXXIV'", "assert module['roman'](1) == 'I'"]),
    # --- data structures ----------------------------------------------------
    ("dedup", "dedup", "Write dedup(items) that returns the list with duplicates removed, keeping the first occurrence order.",
     "def dedup(items):\n    seen = set(); out = []\n    for x in items:\n        if x not in seen:\n            seen.add(x); out.append(x)\n    return out",
     ["assert module['dedup']([1, 1, 2, 1, 3]) == [1, 2, 3]", "assert module['dedup']([]) == []", "assert module['dedup'](['a', 'a']) == ['a']"]),
    ("chunk", "chunk", "Write chunk(items, size) that splits a list into consecutive sublists of length size (the last may be shorter); size >= 1.",
     "def chunk(items, size):\n    return [items[i:i + size] for i in range(0, len(items), size)]",
     ["assert module['chunk']([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]", "assert module['chunk']([], 3) == []", "assert module['chunk']([1], 1) == [[1]]"]),
    ("flatten", "flatten", "Write flatten(nested) that flattens a list of lists into a single list, one level deep.",
     "def flatten(nested):\n    return [x for sub in nested for x in sub]",
     ["assert module['flatten']([[1, 2], [3]]) == [1, 2, 3]", "assert module['flatten']([]) == []", "assert module['flatten']([[], [1]]) == [1]"]),
    ("group-by-parity", "group_by_parity", "Write group_by_parity(nums) that returns a dict with keys 'even' and 'odd' mapping to lists of those numbers, preserving order.",
     "def group_by_parity(nums):\n    d = {'even': [], 'odd': []}\n    for n in nums:\n        d['even' if n % 2 == 0 else 'odd'].append(n)\n    return d",
     ["assert module['group_by_parity']([1, 2, 3, 4]) == {'even': [2, 4], 'odd': [1, 3]}", "assert module['group_by_parity']([]) == {'even': [], 'odd': []}"]),
    ("merge-dicts", "merge_dicts", "Write merge_dicts(a, b) that returns a new dict with the entries of a and b; on key conflicts b wins. Inputs are not modified.",
     "def merge_dicts(a, b):\n    out = dict(a); out.update(b); return out",
     ["assert module['merge_dicts']({'x': 1}, {'y': 2}) == {'x': 1, 'y': 2}", "assert module['merge_dicts']({'x': 1}, {'x': 9}) == {'x': 9}", "assert module['merge_dicts']({}, {}) == {}"]),
    ("invert-dict", "invert_dict", "Write invert_dict(d) that returns a dict mapping each value back to its key (values are unique and hashable).",
     "def invert_dict(d):\n    return {v: k for k, v in d.items()}",
     ["assert module['invert_dict']({'a': 1, 'b': 2}) == {1: 'a', 2: 'b'}", "assert module['invert_dict']({}) == {}"]),
    ("second-largest", "second_largest", "Write second_largest(nums) that returns the second largest distinct value in a list with at least two distinct values.",
     "def second_largest(nums):\n    u = sorted(set(nums))\n    return u[-2]",
     ["assert module['second_largest']([1, 2, 3]) == 2", "assert module['second_largest']([5, 5, 4]) == 4", "assert module['second_largest']([-1, -2]) == -2"]),
    ("running-total", "running_total", "Write running_total(nums) that returns the list of cumulative sums.",
     "def running_total(nums):\n    out = []; t = 0\n    for n in nums:\n        t += n; out.append(t)\n    return out",
     ["assert module['running_total']([1, 2, 3]) == [1, 3, 6]", "assert module['running_total']([]) == []"]),
    ("transpose", "transpose", "Write transpose(matrix) that returns the transpose of a rectangular list of lists.",
     "def transpose(matrix):\n    return [list(row) for row in zip(*matrix)] if matrix else []",
     ["assert module['transpose']([[1, 2], [3, 4]]) == [[1, 3], [2, 4]]", "assert module['transpose']([[1, 2, 3]]) == [[1], [2], [3]]", "assert module['transpose']([]) == []"]),
    ("balanced-brackets", "balanced_brackets", "Write balanced_brackets(s) that returns True if the brackets ()[]{} in s are correctly matched and nested.",
     "def balanced_brackets(s):\n    pairs = {')': '(', ']': '[', '}': '{'}\n    stack = []\n    for c in s:\n        if c in '([{': stack.append(c)\n        elif c in pairs:\n            if not stack or stack.pop() != pairs[c]: return False\n    return not stack",
     ["assert module['balanced_brackets']('([]{})') is True", "assert module['balanced_brackets']('(]') is False", "assert module['balanced_brackets']('') is True", "assert module['balanced_brackets']('(()') is False"]),
    # --- parsing ------------------------------------------------------------
    ("parse-kv", "parse_kv", "Write parse_kv(s) that parses lines of the form KEY=VALUE into a dict, ignoring blank lines and lines starting with '#'. Later keys override earlier ones.",
     "def parse_kv(s):\n    d = {}\n    for line in s.split('\\n'):\n        line = line.strip()\n        if not line or line.startswith('#') or '=' not in line: continue\n        k, v = line.split('=', 1)\n        d[k.strip()] = v.strip()\n    return d",
     ["assert module['parse_kv']('a=1\\nb=2') == {'a': '1', 'b': '2'}", "assert module['parse_kv']('# c\\n\\na=1') == {'a': '1'}", "assert module['parse_kv']('a=1\\na=2') == {'a': '2'}"]),
    ("parse-csv-line", "parse_csv_line", "Write parse_csv_line(s) that splits a simple comma-separated line into a list of fields, stripping surrounding spaces from each field (no quoting).",
     "def parse_csv_line(s):\n    return [f.strip() for f in s.split(',')]",
     ["assert module['parse_csv_line']('a, b ,c') == ['a', 'b', 'c']", "assert module['parse_csv_line']('') == ['']", "assert module['parse_csv_line']('x') == ['x']"]),
    ("parse-int-list", "parse_int_list", "Write parse_int_list(s) that returns the list of integers found in a space-separated string, skipping tokens that are not integers.",
     "def parse_int_list(s):\n    out = []\n    for tok in s.split():\n        try:\n            out.append(int(tok))\n        except ValueError:\n            pass\n    return out",
     ["assert module['parse_int_list']('1 2 x 3') == [1, 2, 3]", "assert module['parse_int_list']('') == []", "assert module['parse_int_list']('-4 5') == [-4, 5]"]),
    ("count-log-levels", "count_log_levels", "Write count_log_levels(s) that counts occurrences of the levels INFO, WARN and ERROR as whole first words of each line, returning a dict with those three keys.",
     "def count_log_levels(s):\n    d = {'INFO': 0, 'WARN': 0, 'ERROR': 0}\n    for line in s.split('\\n'):\n        first = line.split()[0] if line.split() else ''\n        if first in d: d[first] += 1\n    return d",
     ["assert module['count_log_levels']('INFO a\\nERROR b\\nINFO c') == {'INFO': 2, 'WARN': 0, 'ERROR': 1}", "assert module['count_log_levels']('') == {'INFO': 0, 'WARN': 0, 'ERROR': 0}"]),
    ("parse-query", "parse_query", "Write parse_query(s) that parses a URL query string like 'a=1&b=2' into a dict; ignore empty pairs. Later keys override earlier ones.",
     "def parse_query(s):\n    d = {}\n    for pair in s.split('&'):\n        if '=' not in pair: continue\n        k, v = pair.split('=', 1)\n        if k: d[k] = v\n    return d",
     ["assert module['parse_query']('a=1&b=2') == {'a': '1', 'b': '2'}", "assert module['parse_query']('') == {}", "assert module['parse_query']('a=1&a=2') == {'a': '2'}"]),
    # --- networking ---------------------------------------------------------
    ("valid-ipv4", "valid_ipv4", "Write valid_ipv4(s) that returns True if s is a valid dotted IPv4 address (four decimal octets 0-255, no leading zeros beyond a single '0').",
     "def valid_ipv4(s):\n    parts = s.split('.')\n    if len(parts) != 4: return False\n    for p in parts:\n        if not p.isdigit(): return False\n        if len(p) > 1 and p[0] == '0': return False\n        if int(p) > 255: return False\n    return True",
     ["assert module['valid_ipv4']('192.168.0.1') is True", "assert module['valid_ipv4']('256.0.0.1') is False", "assert module['valid_ipv4']('1.2.3') is False", "assert module['valid_ipv4']('10.0.01.1') is False"]),
    ("ip-to-int", "ip_to_int", "Write ip_to_int(s) that converts a valid dotted IPv4 address to its 32-bit integer value.",
     "def ip_to_int(s):\n    a, b, c, d = (int(p) for p in s.split('.'))\n    return (a << 24) | (b << 16) | (c << 8) | d",
     ["assert module['ip_to_int']('0.0.0.1') == 1", "assert module['ip_to_int']('255.255.255.255') == 4294967295", "assert module['ip_to_int']('192.168.0.1') == 3232235521"]),
    ("int-to-ip", "int_to_ip", "Write int_to_ip(n) that converts a 32-bit integer to a dotted IPv4 address string.",
     "def int_to_ip(n):\n    return '.'.join(str((n >> shift) & 255) for shift in (24, 16, 8, 0))",
     ["assert module['int_to_ip'](1) == '0.0.0.1'", "assert module['int_to_ip'](3232235521) == '192.168.0.1'", "assert module['int_to_ip'](4294967295) == '255.255.255.255'"]),
    ("netmask-from-prefix", "netmask_from_prefix", "Write netmask_from_prefix(n) that returns the dotted IPv4 netmask for a prefix length 0..32.",
     "def netmask_from_prefix(n):\n    mask = (0xFFFFFFFF << (32 - n)) & 0xFFFFFFFF if n else 0\n    return '.'.join(str((mask >> shift) & 255) for shift in (24, 16, 8, 0))",
     ["assert module['netmask_from_prefix'](24) == '255.255.255.0'", "assert module['netmask_from_prefix'](0) == '0.0.0.0'", "assert module['netmask_from_prefix'](32) == '255.255.255.255'", "assert module['netmask_from_prefix'](16) == '255.255.0.0'"]),
    ("network-address", "network_address", "Write network_address(ip, prefix) that returns the dotted IPv4 network address for the given IP and prefix length 0..32.",
     "def network_address(ip, prefix):\n    a, b, c, d = (int(p) for p in ip.split('.'))\n    value = (a << 24) | (b << 16) | (c << 8) | d\n    mask = (0xFFFFFFFF << (32 - prefix)) & 0xFFFFFFFF if prefix else 0\n    net = value & mask\n    return '.'.join(str((net >> shift) & 255) for shift in (24, 16, 8, 0))",
     ["assert module['network_address']('192.168.1.130', 24) == '192.168.1.0'", "assert module['network_address']('10.1.2.3', 8) == '10.0.0.0'", "assert module['network_address']('192.168.1.130', 25) == '192.168.1.128'"]),
    ("hosts-in-prefix", "hosts_in_prefix", "Write hosts_in_prefix(prefix) that returns the number of usable IPv4 host addresses for a prefix length 0..32 (subtract network and broadcast for prefixes <= 30, else 0).",
     "def hosts_in_prefix(prefix):\n    size = 1 << (32 - prefix)\n    return size - 2 if size >= 4 else 0",
     ["assert module['hosts_in_prefix'](24) == 254", "assert module['hosts_in_prefix'](30) == 2", "assert module['hosts_in_prefix'](31) == 0", "assert module['hosts_in_prefix'](32) == 0"]),
    ("valid-mac", "valid_mac", "Write valid_mac(s) that returns True if s is a MAC address of six colon-separated pairs of hex digits (case-insensitive).",
     "def valid_mac(s):\n    parts = s.split(':')\n    if len(parts) != 6: return False\n    return all(len(p) == 2 and all(c in '0123456789abcdefABCDEF' for c in p) for p in parts)",
     ["assert module['valid_mac']('AA:BB:CC:00:11:22') is True", "assert module['valid_mac']('aabbcc001122') is False", "assert module['valid_mac']('AA:BB:CC:00:11:ZZ') is False"]),
    ("same-subnet", "same_subnet", "Write same_subnet(ip1, ip2, prefix) that returns True if the two dotted IPv4 addresses are in the same network for the given prefix length.",
     "def same_subnet(ip1, ip2, prefix):\n    def val(ip):\n        a, b, c, d = (int(p) for p in ip.split('.'))\n        return (a << 24) | (b << 16) | (c << 8) | d\n    mask = (0xFFFFFFFF << (32 - prefix)) & 0xFFFFFFFF if prefix else 0\n    return (val(ip1) & mask) == (val(ip2) & mask)",
     ["assert module['same_subnet']('192.168.1.5', '192.168.1.9', 24) is True", "assert module['same_subnet']('192.168.1.5', '192.168.2.9', 24) is False", "assert module['same_subnet']('10.0.0.1', '11.0.0.1', 7) is True"]),
    ("valid-port", "valid_port", "Write valid_port(n) that returns True if n is an integer in the TCP/UDP port range 1..65535.",
     "def valid_port(n):\n    return isinstance(n, int) and 1 <= n <= 65535",
     ["assert module['valid_port'](80) is True", "assert module['valid_port'](0) is False", "assert module['valid_port'](70000) is False", "assert module['valid_port'](65535) is True"]),
    # --- sysadmin -----------------------------------------------------------
    ("human-size", "human_size", "Write human_size(n) that formats a byte count as a string with unit B, KiB, MiB or GiB using 1024 steps, one decimal for non-byte units, e.g. 1536 -> '1.5 KiB'.",
     "def human_size(n):\n    units = ['B', 'KiB', 'MiB', 'GiB']\n    size = float(n); i = 0\n    while size >= 1024 and i < len(units) - 1:\n        size /= 1024; i += 1\n    return (f'{int(size)} B' if i == 0 else f'{size:.1f} {units[i]}')",
     ["assert module['human_size'](512) == '512 B'", "assert module['human_size'](1536) == '1.5 KiB'", "assert module['human_size'](1048576) == '1.0 MiB'"]),
    ("basename", "basename", "Write basename(path) that returns the final component of a '/'-separated path, without a trailing slash; the root '/' returns ''.",
     "def basename(path):\n    return path.rstrip('/').split('/')[-1] if path.strip('/') else ''",
     ["assert module['basename']('/a/b/c.txt') == 'c.txt'", "assert module['basename']('/a/b/') == 'b'", "assert module['basename']('/') == ''"]),
    ("join-path", "join_path", "Write join_path(a, b) that joins two path segments with a single '/', avoiding a double slash when a ends with '/'.",
     "def join_path(a, b):\n    return a.rstrip('/') + '/' + b.lstrip('/')",
     ["assert module['join_path']('/a', 'b') == '/a/b'", "assert module['join_path']('/a/', '/b') == '/a/b'", "assert module['join_path']('', 'b') == '/b'"]),
    ("parse-permissions", "parse_permissions", "Write parse_permissions(bits) that converts a 3-digit octal string like '755' to an rwx string like 'rwxr-xr-x'.",
     "def parse_permissions(bits):\n    table = ['---', '--x', '-w-', '-wx', 'r--', 'r-x', 'rw-', 'rwx']\n    return ''.join(table[int(c)] for c in bits)",
     ["assert module['parse_permissions']('755') == 'rwxr-xr-x'", "assert module['parse_permissions']('644') == 'rw-r--r--'", "assert module['parse_permissions']('000') == '---------'"]),
    ("top-n", "top_n", "Write top_n(items, n) that returns the n largest numbers from a list, sorted descending; if n exceeds the length, return all of them sorted descending.",
     "def top_n(items, n):\n    return sorted(items, reverse=True)[:n]",
     ["assert module['top_n']([3, 1, 4, 1, 5], 2) == [5, 4]", "assert module['top_n']([1], 5) == [1]", "assert module['top_n']([], 3) == []"]),
    ("dedup-preserve", "dedup_preserve", "Write dedup_preserve(paths) that removes duplicate strings from a list while keeping the first occurrence, useful for a PATH-like list.",
     "def dedup_preserve(paths):\n    seen = set(); out = []\n    for p in paths:\n        if p not in seen:\n            seen.add(p); out.append(p)\n    return out",
     ["assert module['dedup_preserve'](['/bin', '/usr/bin', '/bin']) == ['/bin', '/usr/bin']", "assert module['dedup_preserve']([]) == []"]),
    ("parse-duration", "parse_duration", "Write parse_duration(s) that converts a string like '1h30m' or '45s' into total seconds; supports h, m, s parts in that order, any subset.",
     "def parse_duration(s):\n    total = 0; num = ''\n    for c in s:\n        if c.isdigit(): num += c\n        else:\n            total += int(num) * {'h': 3600, 'm': 60, 's': 1}[c]; num = ''\n    return total",
     ["assert module['parse_duration']('1h30m') == 5400", "assert module['parse_duration']('45s') == 45", "assert module['parse_duration']('2h') == 7200"]),
    ("cron-field-matches", "cron_field_matches", "Write cron_field_matches(field, value) that returns True if a single cron field ('*', a number, or a comma list of numbers) matches the integer value.",
     "def cron_field_matches(field, value):\n    if field == '*': return True\n    return value in {int(x) for x in field.split(',')}",
     ["assert module['cron_field_matches']('*', 5) is True", "assert module['cron_field_matches']('1,2,3', 2) is True", "assert module['cron_field_matches']('1,2', 5) is False"]),
]

# Second wave — kept AFTER the first 52 so ids arena-001..052 never move
# (older accepted arena solutions keep matching the suite).
EXTRA_TASKS: list[tuple[str, str, str, str, list[str]]] = [
    # --- more text ----------------------------------------------------------
    ("count-words", "count_words", "Write count_words(s) that returns the number of whitespace-separated words in s.",
     "def count_words(s):\n    return len(s.split())",
     ["assert module['count_words']('a b c') == 3", "assert module['count_words']('') == 0", "assert module['count_words']('  x  ') == 1"]),
    ("capitalize-first", "capitalize_first", "Write capitalize_first(s) that uppercases only the first character of s, leaving the rest unchanged.",
     "def capitalize_first(s):\n    return s[:1].upper() + s[1:]",
     ["assert module['capitalize_first']('hello') == 'Hello'", "assert module['capitalize_first']('') == ''", "assert module['capitalize_first']('aBC') == 'ABC'"]),
    ("remove-vowels", "remove_vowels", "Write remove_vowels(s) that returns s without any vowels (aeiou, case-insensitive).",
     "def remove_vowels(s):\n    return ''.join(c for c in s if c.lower() not in 'aeiou')",
     ["assert module['remove_vowels']('Hello') == 'Hll'", "assert module['remove_vowels']('xyz') == 'xyz'", "assert module['remove_vowels']('AEIOU') == ''"]),
    ("repeat-string", "repeat_string", "Write repeat_string(s, n) that returns s repeated n times (n >= 0).",
     "def repeat_string(s, n):\n    return s * n",
     ["assert module['repeat_string']('ab', 3) == 'ababab'", "assert module['repeat_string']('x', 0) == ''", "assert module['repeat_string']('', 5) == ''"]),
    ("longest-word", "longest_word", "Write longest_word(s) that returns the longest whitespace-separated word in s; on a tie the first. Empty string returns ''.",
     "def longest_word(s):\n    words = s.split()\n    if not words: return ''\n    best = words[0]\n    for w in words:\n        if len(w) > len(best): best = w\n    return best",
     ["assert module['longest_word']('a bb ccc') == 'ccc'", "assert module['longest_word']('aa bb') == 'aa'", "assert module['longest_word']('') == ''"]),
    ("count-substring", "count_substring", "Write count_substring(s, sub) that returns the number of non-overlapping occurrences of the non-empty sub in s.",
     "def count_substring(s, sub):\n    return s.count(sub)",
     ["assert module['count_substring']('aaaa', 'aa') == 2", "assert module['count_substring']('abc', 'x') == 0", "assert module['count_substring']('ababab', 'ab') == 3"]),
    ("swap-case", "swap_case", "Write swap_case(s) that returns s with the case of each letter swapped.",
     "def swap_case(s):\n    return s.swapcase()",
     ["assert module['swap_case']('Hello') == 'hELLO'", "assert module['swap_case']('123') == '123'", "assert module['swap_case']('') == ''"]),
    ("initials", "initials", "Write initials(name) that returns the uppercase initials of each whitespace-separated word, concatenated.",
     "def initials(name):\n    return ''.join(w[0].upper() for w in name.split())",
     ["assert module['initials']('john doe') == 'JD'", "assert module['initials']('a b c') == 'ABC'", "assert module['initials']('') == ''"]),
    ("first-non-repeating", "first_non_repeating", "Write first_non_repeating(s) that returns the first character in s that appears exactly once, or '' if none.",
     "def first_non_repeating(s):\n    for c in s:\n        if s.count(c) == 1: return c\n    return ''",
     ["assert module['first_non_repeating']('aabbc') == 'c'", "assert module['first_non_repeating']('aabb') == ''", "assert module['first_non_repeating']('x') == 'x'"]),
    ("normalize-spaces", "normalize_spaces", "Write normalize_spaces(s) that collapses any run of whitespace into a single space and strips the ends.",
     "def normalize_spaces(s):\n    return ' '.join(s.split())",
     ["assert module['normalize_spaces']('  a   b ') == 'a b'", "assert module['normalize_spaces']('') == ''", "assert module['normalize_spaces']('x') == 'x'"]),
    # --- more numbers -------------------------------------------------------
    ("factorial", "factorial", "Write factorial(n) that returns n! for a non-negative integer n, with factorial(0) == 1.",
     "def factorial(n):\n    r = 1\n    for i in range(2, n + 1): r *= i\n    return r",
     ["assert module['factorial'](5) == 120", "assert module['factorial'](0) == 1", "assert module['factorial'](1) == 1"]),
    ("fibonacci", "fibonacci", "Write fibonacci(n) that returns the n-th Fibonacci number with fibonacci(0) == 0 and fibonacci(1) == 1.",
     "def fibonacci(n):\n    a, b = 0, 1\n    for _ in range(n): a, b = b, a + b\n    return a",
     ["assert module['fibonacci'](0) == 0", "assert module['fibonacci'](1) == 1", "assert module['fibonacci'](10) == 55"]),
    ("is-power-of-two", "is_power_of_two", "Write is_power_of_two(n) that returns True if the positive integer n is a power of two.",
     "def is_power_of_two(n):\n    return n > 0 and (n & (n - 1)) == 0",
     ["assert module['is_power_of_two'](8) is True", "assert module['is_power_of_two'](6) is False", "assert module['is_power_of_two'](1) is True"]),
    ("sum-range", "sum_range", "Write sum_range(a, b) that returns the sum of integers from a to b inclusive (a <= b).",
     "def sum_range(a, b):\n    return sum(range(a, b + 1))",
     ["assert module['sum_range'](1, 5) == 15", "assert module['sum_range'](3, 3) == 3", "assert module['sum_range'](-2, 2) == 0"]),
    ("count-divisors", "count_divisors", "Write count_divisors(n) that returns the number of positive divisors of a positive integer n.",
     "def count_divisors(n):\n    c = 0; i = 1\n    while i * i <= n:\n        if n % i == 0:\n            c += 1 if i * i == n else 2\n        i += 1\n    return c",
     ["assert module['count_divisors'](6) == 4", "assert module['count_divisors'](1) == 1", "assert module['count_divisors'](9) == 3"]),
    ("lcm", "lcm", "Write lcm(a, b) that returns the least common multiple of two positive integers.",
     "def lcm(a, b):\n    x, y = a, b\n    while y: x, y = y, x % y\n    return a * b // x",
     ["assert module['lcm'](4, 6) == 12", "assert module['lcm'](3, 5) == 15", "assert module['lcm'](2, 2) == 2"]),
    ("celsius-to-fahrenheit", "celsius_to_fahrenheit", "Write celsius_to_fahrenheit(c) that converts Celsius to Fahrenheit as a float.",
     "def celsius_to_fahrenheit(c):\n    return c * 9 / 5 + 32",
     ["assert module['celsius_to_fahrenheit'](0) == 32.0", "assert module['celsius_to_fahrenheit'](100) == 212.0", "assert abs(module['celsius_to_fahrenheit'](37) - 98.6) < 1e-9"]),
    ("round-half-up", "round_half_up", "Write round_half_up(x) that rounds a non-negative float to the nearest integer, rounding .5 up.",
     "def round_half_up(x):\n    return int(x + 0.5)",
     ["assert module['round_half_up'](2.5) == 3", "assert module['round_half_up'](2.4) == 2", "assert module['round_half_up'](0) == 0"]),
    ("percent-of", "percent_of", "Write percent_of(part, whole) that returns part / whole * 100 as a float; whole is non-zero.",
     "def percent_of(part, whole):\n    return part / whole * 100",
     ["assert module['percent_of'](1, 4) == 25.0", "assert module['percent_of'](3, 3) == 100.0", "assert abs(module['percent_of'](1, 3) - 33.333333333) < 1e-6"]),
    ("nth-triangular", "nth_triangular", "Write nth_triangular(n) that returns the n-th triangular number (0+1+...+n) for n >= 0.",
     "def nth_triangular(n):\n    return n * (n + 1) // 2",
     ["assert module['nth_triangular'](3) == 6", "assert module['nth_triangular'](0) == 0", "assert module['nth_triangular'](10) == 55"]),
    # --- more data structures ----------------------------------------------
    ("sum-list", "sum_list", "Write sum_list(nums) that returns the sum of a list of numbers (empty -> 0).",
     "def sum_list(nums):\n    return sum(nums)",
     ["assert module['sum_list']([1, 2, 3]) == 6", "assert module['sum_list']([]) == 0", "assert module['sum_list']([-1, 1]) == 0"]),
    ("max-list", "max_list", "Write max_list(nums) that returns the maximum of a non-empty list of numbers.",
     "def max_list(nums):\n    m = nums[0]\n    for n in nums:\n        if n > m: m = n\n    return m",
     ["assert module['max_list']([1, 3, 2]) == 3", "assert module['max_list']([-5]) == -5", "assert module['max_list']([4, 4]) == 4"]),
    ("min-list", "min_list", "Write min_list(nums) that returns the minimum of a non-empty list of numbers.",
     "def min_list(nums):\n    m = nums[0]\n    for n in nums:\n        if n < m: m = n\n    return m",
     ["assert module['min_list']([3, 1, 2]) == 1", "assert module['min_list']([9]) == 9", "assert module['min_list']([-1, -2]) == -2"]),
    ("count-occurrences", "count_occurrences", "Write count_occurrences(items, target) that returns how many times target appears in the list items.",
     "def count_occurrences(items, target):\n    return items.count(target)",
     ["assert module['count_occurrences']([1, 2, 1, 1], 1) == 3", "assert module['count_occurrences']([], 5) == 0", "assert module['count_occurrences'](['a'], 'b') == 0"]),
    ("rotate-left", "rotate_left", "Write rotate_left(items, k) that returns the list rotated left by k positions (k >= 0; the list may be empty).",
     "def rotate_left(items, k):\n    if not items: return []\n    k %= len(items)\n    return items[k:] + items[:k]",
     ["assert module['rotate_left']([1, 2, 3, 4], 1) == [2, 3, 4, 1]", "assert module['rotate_left']([1, 2, 3], 3) == [1, 2, 3]", "assert module['rotate_left']([], 2) == []"]),
    ("pairwise-sums", "pairwise_sums", "Write pairwise_sums(nums) that returns the list of sums of each adjacent pair; a list shorter than 2 returns [].",
     "def pairwise_sums(nums):\n    return [nums[i] + nums[i + 1] for i in range(len(nums) - 1)]",
     ["assert module['pairwise_sums']([1, 2, 3]) == [3, 5]", "assert module['pairwise_sums']([5]) == []", "assert module['pairwise_sums']([]) == []"]),
    ("intersection", "intersection", "Write intersection(a, b) that returns the sorted list of values present in both lists, without duplicates.",
     "def intersection(a, b):\n    return sorted(set(a) & set(b))",
     ["assert module['intersection']([1, 2, 3], [2, 3, 4]) == [2, 3]", "assert module['intersection']([1], [2]) == []", "assert module['intersection']([1, 1, 2], [2, 2]) == [2]"]),
    ("list-difference", "list_difference", "Write list_difference(a, b) that returns the values from a not present in b, keeping a's order and duplicates.",
     "def list_difference(a, b):\n    bs = set(b)\n    return [x for x in a if x not in bs]",
     ["assert module['list_difference']([1, 2, 3], [2]) == [1, 3]", "assert module['list_difference']([1, 1, 2], [1]) == [2]", "assert module['list_difference']([], [1]) == []"]),
    ("zip-dict", "zip_dict", "Write zip_dict(keys, values) that builds a dict from parallel lists of keys and values (equal length).",
     "def zip_dict(keys, values):\n    return dict(zip(keys, values))",
     ["assert module['zip_dict'](['a', 'b'], [1, 2]) == {'a': 1, 'b': 2}", "assert module['zip_dict']([], []) == {}", "assert module['zip_dict'](['x'], [9]) == {'x': 9}"]),
    ("count-by", "count_by", "Write count_by(items) that returns a dict mapping each item to its number of occurrences.",
     "def count_by(items):\n    d = {}\n    for x in items:\n        d[x] = d.get(x, 0) + 1\n    return d",
     ["assert module['count_by']([1, 1, 2]) == {1: 2, 2: 1}", "assert module['count_by']([]) == {}", "assert module['count_by'](['a']) == {'a': 1}"]),
    ("max-by-value", "max_by_value", "Write max_by_value(d) that returns the key with the largest value in a non-empty dict; on a tie the smallest key.",
     "def max_by_value(d):\n    best = None\n    for k in sorted(d):\n        if best is None or d[k] > d[best]: best = k\n    return best",
     ["assert module['max_by_value']({'a': 1, 'b': 3}) == 'b'", "assert module['max_by_value']({'a': 2, 'b': 2}) == 'a'", "assert module['max_by_value']({'x': 5}) == 'x'"]),
    ("sort-by-length", "sort_by_length", "Write sort_by_length(words) that returns the list of words sorted by length ascending, stable.",
     "def sort_by_length(words):\n    return sorted(words, key=len)",
     ["assert module['sort_by_length'](['ccc', 'a', 'bb']) == ['a', 'bb', 'ccc']", "assert module['sort_by_length']([]) == []", "assert module['sort_by_length'](['ab', 'cd']) == ['ab', 'cd']"]),
    ("partition", "partition", "Write partition(nums, pivot) that returns a tuple (less, ge): values < pivot then values >= pivot, preserving order.",
     "def partition(nums, pivot):\n    less = [x for x in nums if x < pivot]\n    ge = [x for x in nums if x >= pivot]\n    return (less, ge)",
     ["assert module['partition']([1, 5, 2, 8], 5) == ([1, 2], [5, 8])", "assert module['partition']([], 0) == ([], [])", "assert module['partition']([3, 3], 3) == ([], [3, 3])"]),
    # --- more algorithms ----------------------------------------------------
    ("binary-search", "binary_search", "Write binary_search(sorted_list, target) that returns the index of target in an ascending list, or -1 if absent.",
     "def binary_search(sorted_list, target):\n    lo, hi = 0, len(sorted_list) - 1\n    while lo <= hi:\n        mid = (lo + hi) // 2\n        if sorted_list[mid] == target: return mid\n        if sorted_list[mid] < target: lo = mid + 1\n        else: hi = mid - 1\n    return -1",
     ["assert module['binary_search']([1, 3, 5, 7], 5) == 2", "assert module['binary_search']([1, 2, 3], 4) == -1", "assert module['binary_search']([], 1) == -1"]),
    ("bubble-sort", "bubble_sort", "Write bubble_sort(nums) that returns a new ascending-sorted list using bubble sort; the input is not modified.",
     "def bubble_sort(nums):\n    a = list(nums)\n    for i in range(len(a)):\n        for j in range(len(a) - 1 - i):\n            if a[j] > a[j + 1]: a[j], a[j + 1] = a[j + 1], a[j]\n    return a",
     ["assert module['bubble_sort']([3, 1, 2]) == [1, 2, 3]", "assert module['bubble_sort']([]) == []", "assert module['bubble_sort']([2, 2, 1]) == [1, 2, 2]"]),
    ("merge-sorted", "merge_sorted", "Write merge_sorted(a, b) that merges two ascending-sorted lists into one ascending-sorted list.",
     "def merge_sorted(a, b):\n    i = j = 0; out = []\n    while i < len(a) and j < len(b):\n        if a[i] <= b[j]: out.append(a[i]); i += 1\n        else: out.append(b[j]); j += 1\n    return out + a[i:] + b[j:]",
     ["assert module['merge_sorted']([1, 3], [2, 4]) == [1, 2, 3, 4]", "assert module['merge_sorted']([], [1]) == [1]", "assert module['merge_sorted']([1, 2], []) == [1, 2]"]),
    ("argmax", "argmax", "Write argmax(nums) that returns the index of the maximum value in a non-empty list; on a tie the first index.",
     "def argmax(nums):\n    best = 0\n    for i in range(len(nums)):\n        if nums[i] > nums[best]: best = i\n    return best",
     ["assert module['argmax']([1, 3, 2]) == 1", "assert module['argmax']([5]) == 0", "assert module['argmax']([2, 2]) == 0"]),
    ("is-sorted", "is_sorted", "Write is_sorted(nums) that returns True if the list is in non-decreasing order.",
     "def is_sorted(nums):\n    return all(nums[i] <= nums[i + 1] for i in range(len(nums) - 1))",
     ["assert module['is_sorted']([1, 2, 2, 3]) is True", "assert module['is_sorted']([1, 3, 2]) is False", "assert module['is_sorted']([]) is True"]),
    ("moving-average", "moving_average", "Write moving_average(nums, k) that returns the averages of each window of size k (k >= 1); if the list is shorter than k, return [].",
     "def moving_average(nums, k):\n    return [sum(nums[i:i + k]) / k for i in range(len(nums) - k + 1)]",
     ["assert module['moving_average']([1, 2, 3, 4], 2) == [1.5, 2.5, 3.5]", "assert module['moving_average']([1], 2) == []", "assert module['moving_average']([2, 2, 2], 3) == [2.0]"]),
    ("count-inversions", "count_inversions", "Write count_inversions(nums) that returns the number of pairs (i, j) with i < j and nums[i] > nums[j].",
     "def count_inversions(nums):\n    c = 0\n    for i in range(len(nums)):\n        for j in range(i + 1, len(nums)):\n            if nums[i] > nums[j]: c += 1\n    return c",
     ["assert module['count_inversions']([1, 2, 3]) == 0", "assert module['count_inversions']([3, 2, 1]) == 3", "assert module['count_inversions']([]) == 0"]),
    # --- more bits / encoding ----------------------------------------------
    ("hamming-weight", "hamming_weight", "Write hamming_weight(n) that returns the number of set bits in a non-negative integer n.",
     "def hamming_weight(n):\n    return bin(n).count('1')",
     ["assert module['hamming_weight'](7) == 3", "assert module['hamming_weight'](0) == 0", "assert module['hamming_weight'](8) == 1"]),
    ("hex-to-int", "hex_to_int", "Write hex_to_int(s) that parses a hexadecimal string (no '0x' prefix) into an integer.",
     "def hex_to_int(s):\n    return int(s, 16)",
     ["assert module['hex_to_int']('ff') == 255", "assert module['hex_to_int']('10') == 16", "assert module['hex_to_int']('0') == 0"]),
    ("int-to-hex", "int_to_hex", "Write int_to_hex(n) that returns the lowercase hexadecimal string of a non-negative integer without a '0x' prefix.",
     "def int_to_hex(n):\n    return format(n, 'x')",
     ["assert module['int_to_hex'](255) == 'ff'", "assert module['int_to_hex'](0) == '0'", "assert module['int_to_hex'](16) == '10'"]),
    ("xor-cipher", "xor_cipher", "Write xor_cipher(data, key) that returns a list of ints, each byte of data XORed with key (0..255).",
     "def xor_cipher(data, key):\n    return [b ^ key for b in data]",
     ["assert module['xor_cipher']([1, 2, 3], 0) == [1, 2, 3]", "assert module['xor_cipher']([255], 255) == [0]", "assert module['xor_cipher']([], 5) == []"]),
    ("parity-bit", "parity_bit", "Write parity_bit(n) that returns 1 if the number of set bits in n is odd, else 0.",
     "def parity_bit(n):\n    return bin(n).count('1') % 2",
     ["assert module['parity_bit'](7) == 1", "assert module['parity_bit'](3) == 0", "assert module['parity_bit'](0) == 0"]),
    # --- matrices -----------------------------------------------------------
    ("matrix-sum", "matrix_sum", "Write matrix_sum(matrix) that returns the sum of all elements in a list of lists of numbers.",
     "def matrix_sum(matrix):\n    return sum(sum(row) for row in matrix)",
     ["assert module['matrix_sum']([[1, 2], [3, 4]]) == 10", "assert module['matrix_sum']([]) == 0", "assert module['matrix_sum']([[5]]) == 5"]),
    ("identity-matrix", "identity_matrix", "Write identity_matrix(n) that returns the n x n identity matrix as a list of lists (n >= 0).",
     "def identity_matrix(n):\n    return [[1 if i == j else 0 for j in range(n)] for i in range(n)]",
     ["assert module['identity_matrix'](2) == [[1, 0], [0, 1]]", "assert module['identity_matrix'](0) == []", "assert module['identity_matrix'](1) == [[1]]"]),
    ("diagonal", "diagonal", "Write diagonal(matrix) that returns the main diagonal of a square matrix as a list.",
     "def diagonal(matrix):\n    return [matrix[i][i] for i in range(len(matrix))]",
     ["assert module['diagonal']([[1, 2], [3, 4]]) == [1, 4]", "assert module['diagonal']([]) == []", "assert module['diagonal']([[9]]) == [9]"]),
]

TASKS = TASKS + EXTRA_TASKS


def build_suite() -> dict:
    tasks = []
    for index, (slug, fn, prompt, _solution, asserts) in enumerate(TASKS, start=1):
        tasks.append({
            "id": f"arena-{index:03d}-{slug}",
            "function_name": fn,
            "prompt": prompt,
            "test_source": "\n".join(asserts) + "\n",
        })
    return {"schema_version": SUITE_SCHEMA, "language": "python", "task_count": len(tasks), "tasks": tasks}


def self_validate() -> list[str]:
    """Execute every reference solution against its own tests; return failures."""
    failures = []
    seen_ids: set[str] = set()
    seen_fns: set[str] = set()
    for index, (slug, fn, prompt, solution, asserts) in enumerate(TASKS, start=1):
        task_id = f"arena-{index:03d}-{slug}"
        if task_id in seen_ids:
            failures.append(f"{task_id}: duplicate id")
        seen_ids.add(task_id)
        if fn in seen_fns:
            failures.append(f"{task_id}: duplicate function_name {fn}")
        seen_fns.add(fn)
        if not 12 <= len(prompt) <= 800:
            failures.append(f"{task_id}: prompt length {len(prompt)} out of range")
        try:
            module = {}
            exec(compile(solution, "sol.py", "exec"), module)
            if fn not in module:
                failures.append(f"{task_id}: solution does not define {fn}")
                continue
            exec(compile("\n".join(asserts), "tests.py", "exec"), {"module": module})
        except Exception as error:  # noqa: BLE001 - report any task that is not self-consistent
            failures.append(f"{task_id}: {type(error).__name__}: {error}")
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("configs/arena/practice-suite.v1.json"))
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args(argv)
    failures = self_validate()
    if failures:
        print("SUITE INVALIDE :")
        for line in failures:
            print("  -", line)
        return 1
    suite = build_suite()
    print(f"{suite['task_count']} tâches validées (solution de référence passe ses tests)")
    if not args.check_only:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(suite, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"écrit dans {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
