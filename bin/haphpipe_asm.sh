#! /bin/bash

# Copyright (C) 2019 Matthew L. Bendall

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


SN="haphpipe_asm.sh"
read -r -d '' USAGE <<EOF
$SN [sample_dir] [reference_fasta] <adapters_fasta>

Viral genome assembly from fastq files

EOF

#--- Read command line args
[[ -n "$1" ]] && [[ "$1" == '-h' ]] && echo "$USAGE" && exit 0

[[ -n "$1" ]] && samp="$1"
[[ -n "$2" ]] && ref="$2"
[[ -n "$3" ]] && adapters="$3"

module unload python
module load miniconda3
source activate haphpipe

[[ -e /scratch ]] && export TMPDIR=/scratch

# vppath=/lustre/groups/cbi/Projects/viralpop.git/viralpop
# export PYTHONPATH=$vppath:$PYTHONPATH
# rroot=$(git rev-parse --show-toplevel)

echo "[---$SN---] ($(date)) Starting $SN"

#--- Check that fastq files exist
[[ ! -e "$samp/00_raw/original_1.fastq" ]] && echo "[---$SN---] ($(date)) FAILED: file $samp/00_raw/original_1.fastq does not exist" && exit 1
[[ ! -e "$samp/00_raw/original_2.fastq" ]] && echo "[---$SN---] ($(date)) FAILED: file $samp/00_raw/original_2.fastq does not exist" && exit 1
echo "[---$SN---] ($(date)) Sample:    $samp"

#--- Check that reference exists
[[ ! -e "$ref" ]] && echo "[---$SN---] ($(date)) FAILED: reference index $ref does not exist" && exit 1
echo "[---$SN---] ($(date)) Reference: $ref"

#--- Check adapters if provided
if [[ -n "$adapters" ]]; then
    [[ ! -e "$adapters" ]] && echo "[---$SN---] ($(date)) FAILED: adapters $adapters does not exist" && exit 1
    echo "[---$SN---] ($(date)) Adapters:  $adapters"
    aparam="--adapter_file $adapters"
else
    echo "[---$SN---] ($(date)) Adapters:  $adapters"
    aparam=""
fi

echo "[---$SN---] ($(date)) Ad param:  $aparam"

#--- Start the timer
t1=$(date +"%s")

##########################################################################################
# Step 1: Trim reads.
##########################################################################################
stage="trim_reads"
echo "[---$SN---] ($(date)) Stage: $stage"
mkdir -p $samp/00_trim

echo "hp_assemble trim_reads --ncpu $(nproc) \
    $aparam \
    --fq1 $samp/00_raw/original_1.fastq \
    --fq2 $samp/00_raw/original_2.fastq \
    --outdir $samp/00_trim"

hp_assemble trim_reads --ncpu $(nproc) \
    $aparam \
    --fq1 $samp/00_raw/original_1.fastq \
    --fq2 $samp/00_raw/original_2.fastq \
    --outdir $samp/00_trim

[[ $? -eq 0 ]] && echo "[---$SN---] ($(date)) COMPLETED: $stage" || \
    (  echo "[---$SN---] ($(date)) FAILED: $stage" && exit 1 )

# Symlink to rename files
cd $samp/00_trim && ln -fs trimmed_1.fastq read_1.fq && ln -fs trimmed_2.fastq read_2.fq && cd ../..

##########################################################################################
# Step 2: Join reads with FLASh.
##########################################################################################
stage="join_reads"
echo "[---$SN---] ($(date)) Stage: $stage"
mkdir -p $samp/00_flash

hp_assemble join_reads --ncpu $(nproc) \
    --fq1 $samp/00_trim/read_1.fq \
    --fq2 $samp/00_trim/read_2.fq \
    --max_overlap 150 \
    --outdir $samp/00_flash

[[ $? -eq 0 ]] && echo "[---$SN---] ($(date)) COMPLETED: $stage" || \
    (  echo "[---$SN---] ($(date)) FAILED: $stage" && exit 1 )

cd $samp/00_flash && ln -fs flash.extendedFrags.fastq read_U.fq && cd ../..

##########################################################################################
# Step 3: Error correction using BLESS2
##########################################################################################
stage="ec_reads"
echo "[---$SN---] ($(date)) Stage: $stage"
mkdir -p $samp/00_bless

# bless is not currently available in bioconda
module load bless

hp_assemble ec_reads --ncpu $(nproc) \
    --fq1 $samp/00_trim/read_1.fq \
    --fq2 $samp/00_trim/read_2.fq \
    --kmerlength 31 \
    --outdir $samp/00_bless

[[ $? -eq 0 ]] && echo "[---$SN---] ($(date)) COMPLETED: $stage" || \
    (  echo "[---$SN---] ($(date)) FAILED: $stage" && exit 1 )

cd $samp/00_bless && ln -fs bless.1.corrected.fastq read_1.fq && ln -fs bless.2.corrected.fastq read_2.fq && cd ../..

##########################################################################################
# Step 4: Denovo assembly using Trinity
##########################################################################################

for method in "trim" "bless" "flash"; do
    echo "[---$SN---] ($(date)) Using method $method"
    
    f1arg=$([[ -e $samp/00_${method}/read_1.fq ]] && echo "--fq1 $samp/00_${method}/read_1.fq" || echo "")
    f2arg=$([[ -e $samp/00_${method}/read_2.fq ]] && echo "--fq2 $samp/00_${method}/read_2.fq" || echo "")
    fUarg=$([[ -e $samp/00_${method}/read_U.fq ]] && echo "--fqU $samp/00_${method}/read_U.fq" || echo "")
    
    stage="assemble_denovo"
    echo "[---$SN---] ($(date)) Stage: $stage, $method"
    mkdir -p $samp/04_assembly/$method
        
    hp_assemble assemble_denovo \
        $f1arg $f2arg $fUarg \
        --ncpu $(( $(nproc) - 3 )) --max_memory 50 \
        --outdir $samp/04_assembly/$method
    
    [[ $? -eq 0 ]] && echo "[---$SN---] ($(date)) COMPLETED: $stage" || \
        (  echo "[---$SN---] ($(date)) FAILED: $stage" && exit 1 )
    
##########################################################################################
# Step 5: Assign contigs to subtypes
##########################################################################################
    stage="subtype"
    echo "[---$SN---] ($(date)) Stage: $stage, $method"
    echo "[---$SN---] ($(date)) Skipping subtyping stage"
    # Skip this part now

##########################################################################################
# Step 6: Scaffold contigs
##########################################################################################
    stage="assemble_scaffold"
    echo "[---$SN---] ($(date)) Stage: $stage, $method"
    mkdir -p $samp/06_scaffold/$method
    
    hp_assemble assemble_scaffold --keep_tmp \
            --contigs_fa $samp/04_assembly/$method/contigs.fa \
            --ref_fa $ref \
            --seqname $samp \
            --outdir $samp/06_scaffold/$method
    
    [[ $? -eq 0 ]] && echo "[---$SN---] ($(date)) COMPLETED: $stage" || \
        (  echo "[---$SN---] ($(date)) FAILED: $stage" && exit 1 )

##########################################################################################
# Step 7: Refine alignment 1
##########################################################################################
    stage="refine_alignment (1)"
    echo "[---$SN---] ($(date)) Stage: $stage, $method"
    mkdir -p $samp/07_refine1/$method
    
    # Use the scaffold
    cp $samp/06_scaffold/$method/scaffold.fa $samp/07_refine1/$method/initial.fa
    
    hp_assemble refine_assembly --ncpu 4 \
        $f1arg $f2arg $fUarg \
        --assembly_fa $samp/07_refine1/$method/initial.fa \
        --rgid $samp \
        --min_dp 1 \
        --bt2_preset fast-local \
        --outdir $samp/07_refine1/local \
        --keep_tmp
    
    [[ $? -eq 0 ]] && echo "[---$SN---] ($(date)) COMPLETED: $stage" || \
        (  echo "[---$SN---] ($(date)) FAILED: $stage" && exit 1 )


##########################################################################################
# Step 8: Refine alignment 2
##########################################################################################
    stage="refine_alignment (2)"
    echo "[---$SN---] ($(date)) Stage: $stage, $method"
    mkdir -p $samp/08_refine2/$method
    
    # Copy refined sequence to use for initial
    cp $samp/07_refine1/$method/refined.fa $samp/08_refine2/$method/initial.fa
    
    hp_assemble refine_assembly --ncpu $(nproc) \
        $f1arg $f2arg $fUarg \
        --assembly_fa $samp/08_refine2/$method/initial.fa \
        --rgid $samp \
        --min_dp 1 \
        --bt2_preset sensitive-local \
        --outdir $samp/08_refine2/$method
    
    [[ $? -eq 0 ]] && echo "[---$SN---] ($(date)) COMPLETED: $stage" || \
        (  echo "[---$SN---] ($(date)) FAILED: $stage" && exit 1 )

##########################################################################################
# Step 9: Fix consensus
##########################################################################################
    stage="fix_consensus"
    echo "[---$SN---] ($(date)) Stage: $stage, $method"
    mkdir -p $samp/09_fixed/$method
    
    hp_assemble fix_consensus --ncpu $(nproc) \
        $f1arg $f2arg $fUarg \
        --assembly_fa $samp/08_refine2/$method/refined.fa \
        --rgid $samp \
        --bt2_preset very-sensitive-local \
        --outdir $samp/09_fixed/$method
    
    [[ $? -eq 0 ]] && echo "[---$SN---] ($(date)) COMPLETED: $stage" || \
        (  echo "[---$SN---] ($(date)) FAILED: $stage" && exit 1 )

done

#---Complete job
t2=$(date +"%s")
diff=$(($t2-$t1))
echo "[---$SN---] ($(date)) $(($diff / 60)) minutes and $(($diff % 60)) seconds elapsed."
echo "[---$SN---] ($(date)) $SN COMPLETE."

# Check files
for method in "trim" "bless" "flash"; do
    [[ -e $samp/09_fixed/$method/consensus.fasta ]] && \
    [[ -e $samp/09_fixed/$method/final.bam ]] && \
    [[ -e $samp/09_fixed/$method/variants.ug.vcf.gz ]] && echo "[---$SN---] ($(date)) $samp $method SUCCESS" || echo "[---$SN---] ($(date)) $samp $method FAILED"
done | tee $samp/x.log

[[ $(grep -c 'FAILED' $samp/x.log)  == 0 ]] && echo "[---$SN---] ($(date)) $samp SUCCESS" || echo "[---$SN---] ($(date)) $samp FAILED"
rm -f $samp/x.log
