# -*- coding: utf-8 -*-
"""Utilities for working with GTF files
"""
from __future__ import print_function
from builtins import zip
from builtins import str
from builtins import object
from past.builtins import basestring

import re
import sys

from haphpipe.utils.helpers import cast_str


__author__ = 'Matthew L. Bendall'
__copyright__ = "Copyright (C) 2019 Matthew L. Bendall"


# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

class GTFRow(object):
    cols = [
        ('chrom', str),  ('source', str), ('feature', str),
        ('start', int),  ('end', int),    ('score', str),
        ('strand', str), ('frame', str),
    ]
    # Attributes that should be at the front of attribute string
    ATTRORDER = ['name', 'primary_cds', ]    
    
    def __init__(self, l=None):
        if l is None:
            for n, f in self.cols:
                setattr(self, n, None)
            self.attrs = {}
        else:
            row = l.strip('\n').split('\t')
            for (n, f), val in zip(self.cols, row[:8]):
                try:
                    setattr(self, n, f(val))
                except ValueError:
                    print('WARNING: Did not convert "%s" to %s (%s).' % (val, n, f), file=sys.stderr)
                    setattr(self, n, str(val))
            
            self.attrs = {}
            for k,v in re.findall('(\S+)\s+"([\s\S]+?)";',row[8]):
                self.attrs[k] = cast_str(v)
    
    def gdist(self, other, ignore_strand=False):
        ''' Genomic distance between GTF records '''
        if self.chrom != other.chrom:
            return float('inf')
        if not ignore_strand and self.strand != other.strand:
            return float('inf')
        return max(self.start, other.start) - min(self.end, other.end)
    
    def fmt_attrs(self):
        keyorder = [k for k in self.ATTRORDER if k in self.attrs]
        keyorder += sorted(k for k in self.attrs if k not in self.ATTRORDER)
        return ' '.join('%s "%s";' % (k, self.attrs[k]) for k in keyorder)
    
    def fmt(self):
        return [str(getattr(self, cn)) for cn,ct in self.cols] + [self.fmt_attrs()]
    
    def __str__(self):
        return '\t'.join(self.fmt())

def gtf_parser(infile):
    if isinstance(infile, basestring):
        lines = (l for l in open(infile, 'r'))
    else:
        lines = (l for l in infile)

    for l in lines:
        yield GTFRow(l)

"""
from haphpipe.utils.gtfparse import gtf_parser
from Bio import SeqIO
glines = [gl for gl in gtf_parser('ref/HIV_B.K03455.HXB2.gtf')]
ref = SeqIO.read('ref/HIV_B.K03455.HXB2.fasta', 'fasta')
for gr in glines:
    pc_s, pc_e = map(int, gr.attrs['primary_cds'].split('-'))
    print '%s primary cds' % gr.attrs['name']
    print ref.seq[pc_s-1:pc_e].translate()
    if 'alt_cds' in gr.attrs:
        for x in gr.attrs['alt_cds'].split(','):
            ac_s, ac_e = map(int, x.split('-'))
            print '%s alt cds' % gr.attrs['name']
            print ref.seq[ac_s-1:ac_e].translate()            
"""