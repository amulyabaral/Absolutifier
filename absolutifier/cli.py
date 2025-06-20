import argparse
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import logging
from .processor import compute_absolute_abundance, compute_absolute_abundance_with_error
from .fileutils import list_sequence_files

def main():
    parser = argparse.ArgumentParser(description="Absolutifier - convert relative abundances to absolute")
    parser.add_argument("--counts", required=True, help="CSV file with counts")
    parser.add_argument("--meta", required=True, help="CSV file with concentrations")
    parser.add_argument("--output", required=True, help="Output CSV file")
    parser.add_argument("--volume", type=float, required=True, help="DNA volume (microL), used for all samples")
    parser.add_argument("--fastq_folder", required=True, help="Folder containing sequence files (mandatory)")
    parser.add_argument("--extensions", nargs='*', default=[".fastq", ".fq", ".fasta"], 
                        help="List of sequence file extensions to search for (default: .fastq .fq .fasta)")
    parser.add_argument("--suffixes", nargs="*", help="List of suffixes to filter in files (e.g., _R1 _R2)")
    parser.add_argument("--singleton", nargs="*", help="List of singleton files to include")
    
    # Performance options
    parser.add_argument("--threads", type=int, default=None,
                        help="Number of threads to use for parallel processing (default: all available cores)")
    
    # Error propagation options
    parser.add_argument("--error_bars", action="store_true", 
                       help="Calculate 95% confidence intervals using Monte Carlo sampling")
    parser.add_argument("--mc_samples", type=int, default=1000, 
                       help="Number of Monte Carlo samples for confidence intervals (default: 1000)")
    parser.add_argument("--alpha", type=float, default=0.5,
                       help="Dirichlet prior (pseudocount) for the Bayesian error model (default: 0.5)")
    
    # Plotting options
    parser.add_argument("--plot", action="store_true",
                       help="Generate visualization plots of features across samples with confidence intervals")
    parser.add_argument("--top_features", type=int, default=20,
                       help="Number of top abundant features to show in plots (default: 20)")
    parser.add_argument("--plot_format", choices=["png", "pdf", "svg"], default="png",
                       help="Output format for plots (default: png)")
    parser.add_argument("--figsize", nargs=2, type=float, default=[12, 8],
                       help="Figure size as width height (default: 12 8)")
    
    args = parser.parse_args()

    # --- Setup Logging ---
    logging.basicConfig(level=logging.INFO, 
                        format='%(asctime)s - %(levelname)s - %(message)s',
                        datefmt='%Y-%m-%d %H:%M:%S')
    
    logging.info("Starting Absolutifier run")
    logging.info(f"Using up to {args.threads or 'all available'} threads.")

    # Sequence files are now mandatory
    sequence_files = list_sequence_files(
        folder=args.fastq_folder,
        extensions=args.extensions,
        suffixes=args.suffixes,
        singleton_files=args.singleton
    )
    
    if not sequence_files:
        raise ValueError(f"No sequence files found in {args.fastq_folder} with specified extensions.")
    
    logging.info(f"Found {len(sequence_files)} sequence files.")

    counts = pd.read_csv(args.counts, index_col=0).T
    meta = pd.read_csv(args.meta)
    dna_conc = dict(zip(meta.sample_id, meta.DNA_conc))
    volume = {sample: float(args.volume) for sample in meta.sample_id}

    if args.error_bars:
        logging.info(f"Calculating 95% confidence intervals with {args.mc_samples} Monte Carlo samples...")
        logging.info(f"Using Dirichlet prior with alpha={args.alpha}")
        
        absolute, lower_ci, upper_ci, zero_replaced, scaling_factors = compute_absolute_abundance_with_error(
            counts, dna_conc, volume, sequence_files,
            n_monte_carlo=args.mc_samples,
            alpha=args.alpha,
            n_workers=args.threads
        )
        
        # Create consolidated output with all information including zero-replaced counts and scaling factors
        consolidated_df = create_consolidated_output(counts, absolute, lower_ci, upper_ci, zero_replaced, scaling_factors)
        consolidated_df.to_csv(args.output)
        
        # Save zero-replaced counts separately for transparency
        zero_replaced_output = args.output.replace('.csv', '_zero_replaced.csv')
        zero_replaced.to_csv(zero_replaced_output)
        
        # Save scaling factors separately
        scaling_factors_output = args.output.replace('.csv', '_scaling_factors.csv')
        scaling_factors_df = pd.DataFrame([scaling_factors], index=['scaling_factor'])
        scaling_factors_df.to_csv(scaling_factors_output)
        
        logging.info(f"Results saved:")
        logging.info(f"  - Consolidated results (counts, absolute, CI): {args.output}")
        logging.info(f"  - Zero-replaced counts (for transparency): {zero_replaced_output}")
        logging.info(f"  - Scaling factors: {scaling_factors_output}")
        
        # Generate plots if requested
        if args.plot:
            plot_output_base = args.output.replace('.csv', '')
            plot_absolute_abundances_with_ci(
                counts, absolute, lower_ci, upper_ci,
                plot_output_base, args.top_features, args.plot_format, args.figsize
            )
            logging.info(f"  - Plots saved: {plot_output_base}_*.{args.plot_format}")
        
    else:
        absolute, scaling_factors = compute_absolute_abundance(counts, dna_conc, volume, sequence_files, n_workers=args.threads)
        
        # Create simple consolidated output without confidence intervals but with scaling factors
        consolidated_df = create_simple_consolidated_output(counts, absolute, scaling_factors)
        consolidated_df.to_csv(args.output)
        
        # Save scaling factors separately
        scaling_factors_output = args.output.replace('.csv', '_scaling_factors.csv')
        scaling_factors_df = pd.DataFrame([scaling_factors], index=['scaling_factor'])
        scaling_factors_df.to_csv(scaling_factors_output)
        
        logging.info(f"Absolute abundances saved to: {args.output}")
        logging.info(f"Scaling factors saved to: {scaling_factors_output}")
        
        # Generate plots if requested
        if args.plot:
            plot_output_base = args.output.replace('.csv', '')
            plot_absolute_abundances_simple(
                counts, absolute, plot_output_base, args.top_features, args.plot_format, args.figsize
            )
            logging.info(f"  - Plots saved: {plot_output_base}_*.{args.plot_format}")

def create_consolidated_output(counts_df, absolute_df, lower_ci_df, upper_ci_df, zero_replaced_df, scaling_factors):
    """
    Create a consolidated DataFrame with original counts, absolute abundances, confidence intervals,
    zero-replaced counts, and scaling factors for full transparency.
    
    Output format:
    - Rows: features
    - Columns: sample_name_counts, sample_name_zero_replaced, sample_name_absolute, 
               sample_name_lower_95ci, sample_name_upper_95ci, sample_name_scaling_factor
    """
    consolidated_columns = []
    consolidated_data = []
    
    for sample in counts_df.columns:
        # Add columns for this sample
        consolidated_columns.extend([
            f"{sample}_counts",
            f"{sample}_zero_replaced",
            f"{sample}_absolute", 
            f"{sample}_lower_95ci",
            f"{sample}_upper_95ci",
            f"{sample}_scaling_factor"
        ])
        
        # Create scaling factor column (same value for all features in this sample)
        scaling_factor_column = np.full(len(counts_df), scaling_factors[sample])
        
        # Add data for this sample
        if len(consolidated_data) == 0:
            # Initialize with first sample
            consolidated_data = [
                counts_df[sample].values,
                zero_replaced_df[sample].values,
                absolute_df[sample].values,
                lower_ci_df[sample].values, 
                upper_ci_df[sample].values,
                scaling_factor_column
            ]
        else:
            # Append additional samples
            consolidated_data.extend([
                counts_df[sample].values,
                zero_replaced_df[sample].values,
                absolute_df[sample].values,
                lower_ci_df[sample].values,
                upper_ci_df[sample].values,
                scaling_factor_column
            ])
    
    # Transpose to get correct shape
    consolidated_array = np.array(consolidated_data).T
    
    return pd.DataFrame(
        consolidated_array,
        index=counts_df.index,
        columns=consolidated_columns
    )

def create_simple_consolidated_output(counts_df, absolute_df, scaling_factors):
    """
    Create a simple consolidated DataFrame with original counts, absolute abundances, and scaling factors.
    
    Output format:
    - Rows: features  
    - Columns: sample_name_counts, sample_name_absolute, sample_name_scaling_factor
    """
    consolidated_columns = []
    consolidated_data = []
    
    for sample in counts_df.columns:
        # Add columns for this sample
        consolidated_columns.extend([
            f"{sample}_counts",
            f"{sample}_absolute",
            f"{sample}_scaling_factor"
        ])
        
        # Create scaling factor column (same value for all features in this sample)
        scaling_factor_column = np.full(len(counts_df), scaling_factors[sample])
        
        # Add data for this sample
        if len(consolidated_data) == 0:
            # Initialize with first sample
            consolidated_data = [
                counts_df[sample].values,
                absolute_df[sample].values,
                scaling_factor_column
            ]
        else:
            # Append additional samples
            consolidated_data.extend([
                counts_df[sample].values,
                absolute_df[sample].values,
                scaling_factor_column
            ])
    
    # Transpose to get correct shape
    consolidated_array = np.array(consolidated_data).T
    
    return pd.DataFrame(
        consolidated_array,
        index=counts_df.index,
        columns=consolidated_columns
    )

def plot_absolute_abundances_with_ci(counts_df, absolute_df, lower_ci_df, upper_ci_df, 
                                   output_base, top_features=20, plot_format="png", figsize=[12, 8]):
    """
    Create publication-quality plots showing absolute abundances with confidence intervals.
    
    Parameters:
    -----------
    counts_df : pd.DataFrame
        Original counts
    absolute_df : pd.DataFrame  
        Absolute abundances (point estimates)
    lower_ci_df : pd.DataFrame
        Lower 95% confidence intervals
    upper_ci_df : pd.DataFrame
        Upper 95% confidence intervals
    output_base : str
        Base filename for output plots
    top_features : int
        Number of top abundant features to display
    plot_format : str
        Output format (png, pdf, svg)
    figsize : list
        Figure size [width, height]
    """
    logging.info(f"\n=== GENERATING PUBLICATION-QUALITY PLOTS ===")
    
    # Set publication-style plot parameters
    plt.style.use('default')
    sns.set_palette("husl")
    plt.rcParams.update({
        'font.size': 12,
        'axes.titlesize': 14,
        'axes.labelsize': 12,
        'xtick.labelsize': 10,
        'ytick.labelsize': 10,
        'legend.fontsize': 10,
        'figure.titlesize': 16
    })
    
    # Get top features by mean absolute abundance
    mean_abundance = absolute_df.mean(axis=1).sort_values(ascending=False)
    top_feature_names = mean_abundance.head(top_features).index
    
    logging.info(f"Plotting top {len(top_feature_names)} features by mean absolute abundance")
    
    # Plot 1: Bar plot with error bars for each sample
    n_samples = len(absolute_df.columns)
    fig, axes = plt.subplots(1, n_samples, figsize=(figsize[0] * n_samples/2, figsize[1]), 
                            squeeze=False)
    axes = axes.flatten()
    
    for i, sample in enumerate(absolute_df.columns):
        ax = axes[i]
        
        # Get data for this sample and top features
        sample_absolute = absolute_df.loc[top_feature_names, sample]
        sample_lower = lower_ci_df.loc[top_feature_names, sample]
        sample_upper = upper_ci_df.loc[top_feature_names, sample]
        
        # Calculate error bars
        lower_err = sample_absolute - sample_lower
        upper_err = sample_upper - sample_absolute
        
        # Create bar plot
        x_pos = np.arange(len(top_feature_names))
        bars = ax.bar(x_pos, sample_absolute, yerr=[lower_err, upper_err], 
                     capsize=5, alpha=0.8, color=sns.color_palette("husl", len(top_feature_names)))
        
        ax.set_title(f'Sample: {sample}', fontweight='bold')
        ax.set_xlabel('Features')
        ax.set_ylabel('Absolute Abundance')
        ax.set_xticks(x_pos)
        ax.set_xticklabels([name[:15] + '...' if len(name) > 15 else name 
                           for name in top_feature_names], rotation=45, ha='right')
        ax.grid(True, alpha=0.3)
        
        # Add value labels on bars
        for j, (bar, val) in enumerate(zip(bars, sample_absolute)):
            if val > 0:
                ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + upper_err.iloc[j]*0.1,
                       f'{val:.1e}', ha='center', va='bottom', fontsize=8)
    
    plt.tight_layout()
    plt.savefig(f"{output_base}_barplot_by_sample.{plot_format}", dpi=300, bbox_inches='tight')
    plt.close()
    
    # Plot 2: Heatmap of absolute abundances
    fig, ax = plt.subplots(figsize=figsize)
    
    heatmap_data = absolute_df.loc[top_feature_names].T  # Samples as rows, features as columns
    
    # Use log scale for better visualization if values span many orders of magnitude
    log_data = np.log10(heatmap_data + 1e-10)  # Add small constant to handle zeros
    
    sns.heatmap(log_data, annot=False, cmap='viridis', 
                xticklabels=[name[:20] + '...' if len(name) > 20 else name for name in top_feature_names],
                yticklabels=heatmap_data.index, ax=ax, cbar_kws={'label': 'log10(Absolute Abundance)'})
    
    ax.set_title('Heatmap of Absolute Abundances (log10 scale)', fontweight='bold', pad=20)
    ax.set_xlabel('Features')
    ax.set_ylabel('Samples')
    plt.xticks(rotation=45, ha='right')
    plt.yticks(rotation=0)
    
    plt.tight_layout()
    plt.savefig(f"{output_base}_heatmap.{plot_format}", dpi=300, bbox_inches='tight')
    plt.close()
    
    # Plot 3: Confidence interval comparison across samples for top 5 features
    top_5_features = top_feature_names[:5]
    fig, ax = plt.subplots(figsize=figsize)
    
    x_offset = np.linspace(-0.3, 0.3, len(absolute_df.columns))
    colors = sns.color_palette("husl", len(absolute_df.columns))
    
    for i, sample in enumerate(absolute_df.columns):
        sample_pos = np.arange(len(top_5_features)) + x_offset[i]
        sample_absolute = absolute_df.loc[top_5_features, sample]
        sample_lower = lower_ci_df.loc[top_5_features, sample]
        sample_upper = upper_ci_df.loc[top_5_features, sample]
        
        lower_err = sample_absolute - sample_lower
        upper_err = sample_upper - sample_absolute
        
        ax.errorbar(sample_pos, sample_absolute, yerr=[lower_err, upper_err],
                   fmt='o', capsize=5, label=sample, color=colors[i], markersize=8)
    
    ax.set_xlabel('Features')
    ax.set_ylabel('Absolute Abundance')
    ax.set_title('Top 5 Features: Absolute Abundances with 95% Confidence Intervals', fontweight='bold')
    ax.set_xticks(range(len(top_5_features)))
    ax.set_xticklabels([name[:25] + '...' if len(name) > 25 else name for name in top_5_features],
                      rotation=45, ha='right')
    ax.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
    ax.grid(True, alpha=0.3)
    ax.set_yscale('log')
    
    plt.tight_layout()
    plt.savefig(f"{output_base}_top5_comparison.{plot_format}", dpi=300, bbox_inches='tight')
    plt.close()
    
    logging.info(f"✓ Generated 3 plots:")
    logging.info(f"  - Bar plots by sample: {output_base}_barplot_by_sample.{plot_format}")
    logging.info(f"  - Heatmap: {output_base}_heatmap.{plot_format}")
    logging.info(f"  - Top 5 comparison: {output_base}_top5_comparison.{plot_format}")

def plot_absolute_abundances_simple(counts_df, absolute_df, output_base, top_features=20, 
                                  plot_format="png", figsize=[12, 8]):
    """
    Create plots showing absolute abundances without confidence intervals.
    
    Parameters:
    -----------
    counts_df : pd.DataFrame
        Original counts
    absolute_df : pd.DataFrame
        Absolute abundances
    output_base : str
        Base filename for output plots
    top_features : int
        Number of top abundant features to display
    plot_format : str
        Output format (png, pdf, svg)
    figsize : list
        Figure size [width, height]
    """
    logging.info(f"\n=== GENERATING PLOTS (NO CONFIDENCE INTERVALS) ===")
    
    # Set plot parameters
    plt.style.use('default')
    sns.set_palette("husl")
    plt.rcParams.update({
        'font.size': 12,
        'axes.titlesize': 14,
        'axes.labelsize': 12,
        'xtick.labelsize': 10,
        'ytick.labelsize': 10,
        'legend.fontsize': 10,
        'figure.titlesize': 16
    })
    
    # Get top features by mean absolute abundance
    mean_abundance = absolute_df.mean(axis=1).sort_values(ascending=False)
    top_feature_names = mean_abundance.head(top_features).index
    
    logging.info(f"Plotting top {len(top_feature_names)} features by mean absolute abundance")
    
    # Plot 1: Bar plot for each sample
    n_samples = len(absolute_df.columns)
    fig, axes = plt.subplots(1, n_samples, figsize=(figsize[0] * n_samples/2, figsize[1]), 
                            squeeze=False)
    axes = axes.flatten()
    
    for i, sample in enumerate(absolute_df.columns):
        ax = axes[i]
        
        # Get data for this sample and top features
        sample_absolute = absolute_df.loc[top_feature_names, sample]
        
        # Create bar plot
        x_pos = np.arange(len(top_feature_names))
        bars = ax.bar(x_pos, sample_absolute, alpha=0.8, 
                     color=sns.color_palette("husl", len(top_feature_names)))
        
        ax.set_title(f'Sample: {sample}', fontweight='bold')
        ax.set_xlabel('Features')
        ax.set_ylabel('Absolute Abundance')
        ax.set_xticks(x_pos)
        ax.set_xticklabels([name[:15] + '...' if len(name) > 15 else name 
                           for name in top_feature_names], rotation=45, ha='right')
        ax.grid(True, alpha=0.3)
        
        # Add value labels on bars
        for bar, val in zip(bars, sample_absolute):
            if val > 0:
                ax.text(bar.get_x() + bar.get_width()/2, bar.get_height()*1.02,
                       f'{val:.1e}', ha='center', va='bottom', fontsize=8)
    
    plt.tight_layout()
    plt.savefig(f"{output_base}_barplot_by_sample.{plot_format}", dpi=300, bbox_inches='tight')
    plt.close()
    
    # Plot 2: Heatmap of absolute abundances
    fig, ax = plt.subplots(figsize=figsize)
    
    heatmap_data = absolute_df.loc[top_feature_names].T  # Samples as rows, features as columns
    
    # Use log scale for better visualization
    log_data = np.log10(heatmap_data + 1e-10)  # Add small constant to handle zeros
    
    sns.heatmap(log_data, annot=False, cmap='viridis',
                xticklabels=[name[:20] + '...' if len(name) > 20 else name for name in top_feature_names],
                yticklabels=heatmap_data.index, ax=ax, cbar_kws={'label': 'log10(Absolute Abundance)'})
    
    ax.set_title('Heatmap of Absolute Abundances (log10 scale)', fontweight='bold', pad=20)
    ax.set_xlabel('Features')
    ax.set_ylabel('Samples')
    plt.xticks(rotation=45, ha='right')
    plt.yticks(rotation=0)
    
    plt.tight_layout()
    plt.savefig(f"{output_base}_heatmap.{plot_format}", dpi=300, bbox_inches='tight')
    plt.close()
    
    logging.info(f"✓ Generated 2 plots:")
    logging.info(f"  - Bar plots by sample: {output_base}_barplot_by_sample.{plot_format}")
    logging.info(f"  - Heatmap: {output_base}_heatmap.{plot_format}")
