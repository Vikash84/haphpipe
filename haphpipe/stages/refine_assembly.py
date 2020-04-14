#! /usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import print_function
from __future__ import absolute_import

from builtins import map
from builtins import str
from builtins import zip
from builtins import range
import sys
import os
import shutil
import re
import argparse
import random
from collections import OrderedDict

from Bio import SeqIO
from Bio import pairwise2

from haphpipe.utils import sysutils
from haphpipe.utils import sequtils
from haphpipe.stages import align_reads
from haphpipe.stages import call_variants
from haphpipe.stages import vcf_to_consensus
from haphpipe.stages import sample_reads
from haphpipe.utils.sysutils import MissingRequiredArgument
from haphpipe.utils.sysutils import PipelineStepError


__author__ = 'Matthew L. Bendall'
__copyright__ = "Copyright (C) 2019 Matthew L. Bendall"

def stageparser(parser):
    """ Add stage-specific options to argparse parser

    Args:
        parser (argparse.ArgumentParser): ArgumentParser object

    Returns:
        None

    """
    group1 = parser.add_argument_group('Input/Output')
    group1.add_argument('--fq1', type=sysutils.existing_file,
                        help='Fastq file with read 1')
    group1.add_argument('--fq2', type=sysutils.existing_file,
                        help='Fastq file with read 2')
    group1.add_argument('--fqU', type=sysutils.existing_file,
                        help='Fastq file with unpaired reads')
    group1.add_argument('--ref_fa', type=sysutils.existing_file, required=True,
                        help='Assembly to refine')
    group1.add_argument('--outdir', type=sysutils.existing_dir, default='.',
                        help='Output directory')
    
    group2 = parser.add_argument_group('Refinement options')
    group2.add_argument('--max_step', type=int, default=1,
                        help='Maximum number of refinement steps')
    group2.add_argument('--subsample', type=int,
                        help='Use a subsample of reads for refinement.')
    group2.add_argument('--seed', type=int,
                        help='''Seed for random number generator (ignored if
                                not subsampling).''')
    group2.add_argument('--sample_id', default='sampleXX',
                        help='Sample ID. Used as read group ID in BAM')

    group3 = parser.add_argument_group('Settings')
    group3.add_argument('--ncpu', type=int, default=1,
                        help='Number of CPUs to use')
    group3.add_argument('--xmx', type=int,
                        default=sysutils.get_java_heap_size(),
                        help='Maximum heap size for Java VM, in GB.')
    group3.add_argument('--keep_tmp', action='store_true',
                        help='Do not delete temporary directory')
    group3.add_argument('--quiet', action='store_true',
                        help='''Do not write output to console
                                (silence stdout and stderr)''')
    group3.add_argument('--logfile', type=argparse.FileType('a'),
                        help='Append console output to this file')
    group3.add_argument('--debug', action='store_true',
                        help='Print commands but do not run')
    parser.set_defaults(func=refine_assembly)

###--Uzma--Like with denovo_assemble, I'm not sure how a wrapper function works and when/why you would implement it
def refine_assembly(**kwargs):
    max_step = kwargs.pop('max_step')
    if max_step == 1:
        kwargs['iteration'] = None
        return refine_assembly_step(**kwargs)
    else:
        kwargs['max_step'] = max_step
        return progressive_refine_assembly(**kwargs)


def refine_assembly_step(
        fq1=None, fq2=None, fqU=None, ref_fa=None, outdir='.',
        iteration=None, subsample=None, seed=None, sample_id='sampleXX',
        ncpu=1, xmx=sysutils.get_java_heap_size(),
        keep_tmp=False, quiet=False, logfile=None, debug=False,
    ):
    # Temporary directory
    tempdir = sysutils.create_tempdir('refine_assembly', None, quiet, logfile)
   
    if subsample is not None:
        seed = seed if seed is not None else random.randrange(1, 1000)
        full1, full2, fullU = fq1, fq2, fqU
        fq1, fq2, fqU = sample_reads.sample_reads(
            fq1=full1, fq2=full2, fqU=fullU, outdir=tempdir,
            nreads=subsample, seed=seed,
            quiet=False, logfile=logfile, debug=debug
        )

    # Align to reference
    tmp_aligned, tmp_bt2 = align_reads.align_reads(
        fq1=fq1, fq2=fq2, fqU=fqU, ref_fa=ref_fa, outdir=tempdir,
        ncpu=ncpu, xmx=xmx, sample_id=sample_id,
        keep_tmp=keep_tmp, quiet=quiet, logfile=logfile, debug=debug,
    )

    # Call variants
    tmp_vcf = call_variants.call_variants(
        aln_bam=tmp_aligned, ref_fa=ref_fa, outdir=tempdir,
        emit_all=True,
        ncpu=ncpu, xmx=xmx,
        keep_tmp=keep_tmp, quiet=quiet, logfile=logfile, debug=debug,
    )

    # Generate consensus
    tmp_fasta = vcf_to_consensus.vcf_to_consensus(
        vcf=tmp_vcf, outdir=tempdir, sampidx=0,
        keep_tmp=keep_tmp, quiet=quiet, logfile=logfile
    )

    # Copy command
    if iteration is None:
        out_refined = os.path.join(outdir, 'refined.fna')
        out_bt2 = os.path.join(outdir, 'refined_bt2.out')
    else:
        out_refined = os.path.join(outdir, 'refined.%02d.fna' % iteration)  ###--Uzma--Each iteration output given different filename?
        out_bt2 = os.path.join(outdir, 'refined_bt2.%02d.out' % iteration)

    shutil.copy(tmp_fasta, out_refined)
    shutil.copy(tmp_bt2, out_bt2)

    if not keep_tmp:
        sysutils.remove_tempdir(tempdir, 'refine_assembly', quiet, logfile)

    return out_refined, out_bt2

###--Uzma--refine_assembly() create for use withing progressive_refine_assembly() ? Like align_reads and call_variants is 
###--within refine_assembly() ?
def progressive_refine_assembly(
        fq1=None, fq2=None, fqU=None, ref_fa=None, outdir='.',
        max_step=None, subsample=None, seed=None, sample_id='sampleXX', ###--Uzma--How does syntax of sampleXX work?
        ncpu=1, xmx=sysutils.get_java_heap_size(),
        keep_tmp=False, quiet=False, logfile=None, debug=False,
    ):

    # Outputs
    out_refined = os.path.join(outdir, 'refined.fna')
    out_bt2 = os.path.join(outdir, 'refined_bt2.out')
    out_summary = os.path.join(outdir, 'refined_summary.out')

    #--- Initialize
    cur_asm = ref_fa
    cur_alnrate = None
    assemblies = [OrderedDict(), ] ###--Uzma--What is OrderDict? How does the syntax work?
    ###--Uzma--Last index of list is contains sequence header. Is this like list.append() ?
    for s in SeqIO.parse(cur_asm, 'fasta'):
        assemblies[-1][s.id] = s
        
    
    # Message log for summary
    ###--Uzma--What are diffs and alnrate have not been set to anything at this stage?
    summary = [
        ['iteration', 'alnrate', 'diffs'] + ['diff:%s' % s for s in assemblies[0].keys()]
    ]

    # Seed random number generator
    random.seed(seed)
    
    ###--Uzma--for loop for iterative refinement?
    for i in range(1, max_step+1):
        # Generate a refined assembly
        tmp_refined, tmp_bt2 = refine_assembly_step(
            fq1=fq1, fq2=fq2, fqU=fqU, ref_fa=cur_asm, outdir=outdir,
            iteration=i, subsample=subsample, sample_id=sample_id,
            ncpu=ncpu, xmx=xmx, keep_tmp=keep_tmp,
            quiet=True, logfile=logfile, debug=debug
        )

        # Check whether alignments are different
        ###--Uzma--Outputs of two consecutive refine_assembly() outputs are compared to see if there is additional improvement?
        diffs = OrderedDict()
        new_seqs = OrderedDict((s.id, s) for s in SeqIO.parse(tmp_refined, 'fasta'))
        for id1, seq1 in new_seqs.items():
            poss0 = [k for k in assemblies[-1].keys() if sequtils.seqid_match(id1, k)]
            if len(poss0) == 1:
                seq0 = assemblies[-1][poss0[0]]
             ###--Uzma--Why did you want to raise PipelineStepError here? If alignments differ, does that not mean more 
             ###--iterative refinements are needed?
            else:
                raise PipelineStepError("Could not match sequence %s" % id1)
            ###--Uzma--Do a global alignment 
            alns = pairwise2.align.globalms(seq1.seq, seq0.seq, 2, -1, -3, -1)
            ###--Uzma--Not sure what all the variables mean
            d = min(sum(nc != cc for nc, cc in zip(t[0], t[1])) for t in alns)
            diffs[id1] = d

        total_diffs = sum(diffs.values())

        # Check new alignment rate
        with open(tmp_bt2, 'rU') as fh:
            bt2str = fh.read()
            m = re.search('(\d+\.\d+)\% overall alignment rate', bt2str)
            if m is None:
                msg = "Alignment rate not found in bowtie2 output."
                msg += "Output file contents:\n%s\n" % bt2str
                msg += "Aborting."
                raise PipelineStepError(msg)
            else:
                new_alnrate = float(m.group(1))

        # Create messages for log
        ###--Uzma--from here to line 237 I'm unsure of what's going on
        row = [str(i), '%.02f' % new_alnrate, '%d' % total_diffs, ]
        for k0 in assemblies[0].keys():
            poss1 = [k for k in diffs.keys() if sequtils.seqid_match(k, k0)]
            if len(poss1) == 0:
                row.append('FAIL')
            elif len(poss1) == 1:
                row.append(str(diffs[poss1[0]]))
            else:
                raise PipelineStepError("Multiple matches for %s" % k0)
        ######row += list(map(str, diffs.values()))
        summary.append(row)

        # Create messages for console
        sysutils.log_message('\nRefinement result:\n', quiet, logfile)
        sysutils.log_message('\tDifferences:\n', quiet, logfile)
        for s,d in diffs.items():
            sysutils.log_message('\t\t%s\t%d\n' % (s,d), quiet, logfile)
        if total_diffs > 0:
            msg = '\t%d differences found with previous\n' % total_diffs
        else:
            msg = '\tNo differences with previous\n'
        sysutils.log_message(msg, quiet, logfile)

        if cur_alnrate is None:
            msg = '\tAlignment rate: %0.2f\n' % new_alnrate
        elif new_alnrate > cur_alnrate:
            msg = '\tAlignment rate has improved: '
            msg += '%.02f > %.02f\n' % (new_alnrate, cur_alnrate)
        else:
            msg = '\tAlignment rate has not improved: '
            msg += '%.02f <= %.02f\n' % (new_alnrate, cur_alnrate)
        sysutils.log_message(msg, quiet, logfile)

        # Decide whether to keep going
        keep_going = True
        if total_diffs == 0:
            keep_going = False
            sysutils.log_message('Stopping: no differences found\n', quiet, logfile)

        # We should also quit if alignment rate does not improve
        # However, subsampling reads can lead to changes in alignment rate
        # that can be ignore. When subsampling is implemented the first
        # boolean value should check whether subsampling is enabled
        if subsample is None: # not subsampling
            if cur_alnrate is not None and new_alnrate <= cur_alnrate:
                keep_going = False
                msg = 'Stopping: alignment rate did not improve\n'
                sysutils.log_message(msg, quiet, logfile)
        
        cur_asm = tmp_refined
        cur_alnrate = new_alnrate
        assemblies.append(new_seqs)

        if not keep_going:
            break

    # Final outputs
    shutil.copy(cur_asm, out_refined)
    shutil.copy(tmp_bt2, out_bt2)

    with open(out_summary, 'w') as outh:
        print('\n'.join('\t'.join(r) for r in summary), file=outh)

    return out_refined, out_bt2, out_summary


def console():
    """ Entry point

    Returns:
        None

    """
    parser = argparse.ArgumentParser(
        description='''Three step assembly refinement: align reads, call
                       variants, and update reference.''',
        formatter_class=sysutils.ArgumentDefaultsHelpFormatterSkipNone,
    )
    stageparser(parser)
    args = parser.parse_args()
    try:
        args.func(**sysutils.args_params(args))
    except MissingRequiredArgument as e:
        parser.print_usage()
        print('error: %s' % e, file=sys.stderr)



if __name__ == '__main__':
    console()
