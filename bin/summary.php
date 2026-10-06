#!/usr/bin/env php
<?php
declare(strict_types=1);

/*
 * CGM rolling summary for minute-grid CSV data.
 *
 * Input:
 *   column 0       YYYYMMDD
 *   columns 1-1440 glucose readings for 00:00-23:59 UTC
 *
 * Designed for up to 366 days of minute-resolution data.
 */

const LOW = 70;
const TIGHT_140 = 140;
const TIGHT_160 = 160;
const TARGET_HIGH = 180;
const VERY_HIGH = 250;
const VERY_LOW = 54;
// LibreLink can delay readings for up to a 20-minute reporting window.
const MAX_GAP_MINUTES = 20;
const STEADY_TOLERANCE = 10;

function usage(): never
{
    echo <<<'TXT'
Usage: php summary.php FILE.csv

Generate rolling CGM summaries ending at the latest recorded glucose value.

Windows shown when enough elapsed history exists:
  1 day
  7 days
  14 days
  30 days
  90 days
  6 months (183 days)
  1 year (365 days)

Each window reports:
  - data coverage
  - mean glucose
  - estimated GMI
  - standard deviation
  - coefficient of variation (CV)
  - time in 70-180, 70-160, and 70-140 mg/dL
  - time >180, >250, <70, and <54 mg/dL
  - longest continuous 70-180, 70-160, 70-140, and <=180 streaks
  - best locally stable in-range plateau using a ±10 mg/dL anchor tolerance

Missing readings do not count toward percentages.
More than 20 consecutive missing minutes breaks a continuity/steady-state streak.

All timestamps are UTC.

Example:
  php summary.php history.csv

TXT;
    exit(0);
}

function fail(string $message): never
{
    fwrite(STDERR, "Error: {$message}\n");
    exit(1);
}

function fmtTs(int $ts): string
{
    return gmdate('Y-m-d H:i', $ts);
}

function fmtDuration(int $minutes): string
{
    if ($minutes < 60) {
        return "{$minutes} min";
    }

    $hours = intdiv($minutes, 60);
    $mins = $minutes % 60;

    if ($hours < 24) {
        return sprintf('%d h %02d min', $hours, $mins);
    }

    $days = intdiv($hours, 24);
    $hours %= 24;

    return sprintf('%d d %02d h %02d min', $days, $hours, $mins);
}

function pct(int $part, int $total): string
{
    return $total > 0
        ? sprintf('%.1f%%', ($part * 100.0) / $total)
        : 'n/a';
}

/** Return index of first point whose timestamp is >= $target. */
function lowerBound(array $points, int $target): int
{
    $lo = 0;
    $hi = count($points);

    while ($lo < $hi) {
        $mid = ($lo + $hi) >> 1;

        if ($points[$mid][0] < $target) {
            $lo = $mid + 1;
        } else {
            $hi = $mid;
        }
    }

    return $lo;
}

function makeStreakState(): array
{
    return [
        'start' => null,
        'end' => null,
        'min' => PHP_INT_MAX,
        'max' => PHP_INT_MIN,
        'best' => null,
    ];
}

function finishStreak(array &$state): void
{
    if ($state['start'] === null || $state['end'] === null) {
        return;
    }

    $minutes = intdiv($state['end'] - $state['start'], 60) + 1;
    $candidate = [
        'start' => $state['start'],
        'end' => $state['end'],
        'minutes' => $minutes,
        'min' => $state['min'],
        'max' => $state['max'],
    ];

    if ($state['best'] === null || $minutes > $state['best']['minutes']) {
        $state['best'] = $candidate;
    }

    $state['start'] = null;
    $state['end'] = null;
    $state['min'] = PHP_INT_MAX;
    $state['max'] = PHP_INT_MIN;
}

function updateStreak(array &$state, int $ts, int $value, bool $matches): void
{
    if (!$matches) {
        finishStreak($state);
        return;
    }

    if ($state['start'] === null) {
        $state['start'] = $ts;
    }

    $state['end'] = $ts;
    $state['min'] = min($state['min'], $value);
    $state['max'] = max($state['max'], $value);
}

/**
 * Compute all threshold streaks in one pass over observed readings.
 * A gap > MAX_GAP_MINUTES breaks all streaks.
 */
function thresholdStreaks(array $points, int $from, int $to): array
{
    $states = [
        '70-180' => makeStreakState(),
        '70-160' => makeStreakState(),
        '70-140' => makeStreakState(),
        '<=180' => makeStreakState(),
    ];

    $lastTs = null;

    for ($i = $from; $i < $to; $i++) {
        [$ts, $v] = $points[$i];

        if ($lastTs !== null) {
            $missing = intdiv($ts - $lastTs, 60) - 1;
            if ($missing > MAX_GAP_MINUTES) {
                foreach ($states as &$state) {
                    finishStreak($state);
                }
                unset($state);
            }
        }

        updateStreak($states['70-180'], $ts, $v, $v >= 70 && $v <= 180);
        updateStreak($states['70-160'], $ts, $v, $v >= 70 && $v <= 160);
        updateStreak($states['70-140'], $ts, $v, $v >= 70 && $v <= 140);
        updateStreak($states['<=180'], $ts, $v, $v <= 180);

        $lastTs = $ts;
    }

    foreach ($states as &$state) {
        finishStreak($state);
    }
    unset($state);

    return [
        '70-180' => $states['70-180']['best'],
        '70-160' => $states['70-160']['best'],
        '70-140' => $states['70-140']['best'],
        '<=180' => $states['<=180']['best'],
    ];
}

/**
 * Linear-time anchor-based steady-state search.
 *
 * A window is valid when:
 *   - all readings are 70..180
 *   - every reading remains within ±$tolerance of the FIRST reading
 *   - no missing run exceeds $maxGap minutes
 *
 * This preserves the anchor semantics of find-steady-states.php without
 * the O(n²) nested scan.
 */
function bestSteadyInRange(
    array $points,
    int $from,
    int $to,
    int $tolerance = STEADY_TOLERANCE,
    int $maxGap = MAX_GAP_MINUTES
): ?array {
    $best = null;
    $left = $from;

    // Monotonic queues storing point indexes for current min/max.
    $minQ = [];
    $maxQ = [];
    $minHead = 0;
    $maxHead = 0;

    $reset = static function (int $nextLeft) use (&$left, &$minQ, &$maxQ, &$minHead, &$maxHead): void {
        $left = $nextLeft;
        $minQ = [];
        $maxQ = [];
        $minHead = 0;
        $maxHead = 0;
    };

    for ($right = $from; $right < $to; $right++) {
        [$ts, $v] = $points[$right];

        if ($right > $from) {
            $previousTs = $points[$right - 1][0];
            $missing = intdiv($ts - $previousTs, 60) - 1;
            if ($missing > $maxGap) {
                $reset($right);
            }
        }

        if ($v < LOW || $v > TARGET_HIGH) {
            $reset($right + 1);
            continue;
        }

        while (count($minQ) > $minHead && $points[$minQ[array_key_last($minQ)]][1] >= $v) {
            array_pop($minQ);
        }
        $minQ[] = $right;

        while (count($maxQ) > $maxHead && $points[$maxQ[array_key_last($maxQ)]][1] <= $v) {
            array_pop($maxQ);
        }
        $maxQ[] = $right;

        // Move the anchor forward until all values fit within anchor ± tolerance.
        while ($left <= $right) {
            $anchor = $points[$left][1];
            $curMin = $points[$minQ[$minHead]][1];
            $curMax = $points[$maxQ[$maxHead]][1];

            if ($curMin >= $anchor - $tolerance && $curMax <= $anchor + $tolerance) {
                break;
            }

            if ($minQ[$minHead] === $left) {
                $minHead++;
            }
            if ($maxQ[$maxHead] === $left) {
                $maxHead++;
            }
            $left++;

            // Periodically compact queues so year-long runs don't retain huge arrays.
            if ($minHead > 1024 && $minHead > count($minQ) / 2) {
                $minQ = array_slice($minQ, $minHead);
                $minHead = 0;
            }
            if ($maxHead > 1024 && $maxHead > count($maxQ) / 2) {
                $maxQ = array_slice($maxQ, $maxHead);
                $maxHead = 0;
            }
        }

        if ($left <= $right) {
            $startTs = $points[$left][0];
            $minutes = intdiv($ts - $startTs, 60) + 1;

            if ($best === null || $minutes > $best['minutes']) {
                $anchor = $points[$left][1];
                $curMin = $points[$minQ[$minHead]][1];
                $curMax = $points[$maxQ[$maxHead]][1];

                $best = [
                    'start' => $startTs,
                    'end' => $ts,
                    'minutes' => $minutes,
                    'min' => $curMin,
                    'max' => $curMax,
                    'center' => $anchor,
                    'actual' => max(abs($curMin - $anchor), abs($curMax - $anchor)),
                ];
            }
        }
    }

    return $best;
}

function printStreak(string $label, ?array $s): void
{
    if ($s === null) {
        printf("  %-30s %s\n", $label . ':', 'n/a');
        return;
    }

    printf(
        "  %-30s %-15s %s -> %s  (%d-%d)\n",
        $label . ':',
        fmtDuration($s['minutes']),
        fmtTs($s['start']),
        fmtTs($s['end']),
        $s['min'],
        $s['max']
    );
}

if ($argc !== 2 || in_array($argv[1] ?? '', ['-h', '--help'], true)) {
    usage();
}

$file = $argv[1];

if (!is_file($file)) {
    fail("file not found: {$file}");
}

$fh = fopen($file, 'rb');
if ($fh === false) {
    fail("unable to open: {$file}");
}

$points = [];
$firstDateTs = null;
$lastDateTs = null;

while (($row = fgetcsv($fh)) !== false) {
    if (!isset($row[0])) {
        continue;
    }

    $date = trim((string)$row[0]);
    if (!preg_match('/^\d{8}$/', $date)) {
        continue;
    }

    $year = (int)substr($date, 0, 4);
    $month = (int)substr($date, 4, 2);
    $day = (int)substr($date, 6, 2);

    if (!checkdate($month, $day, $year)) {
        continue;
    }

    $dayTs = gmmktime(0, 0, 0, $month, $day, $year);
    $firstDateTs ??= $dayTs;
    $lastDateTs = $dayTs;

    for ($minute = 0; $minute < 1440; $minute++) {
        $raw = trim((string)($row[$minute + 1] ?? ''));

        if ($raw === '' || !is_numeric($raw)) {
            continue;
        }

        $value = (int)round((float)$raw);
        $points[] = [$dayTs + ($minute * 60), $value];
    }
}

fclose($fh);

if ($points === []) {
    fail('no glucose readings found');
}

// Normal input is already chronological. Sort only if needed.
$needsSort = false;
for ($i = 1, $n = count($points); $i < $n; $i++) {
    if ($points[$i][0] < $points[$i - 1][0]) {
        $needsSort = true;
        break;
    }
}
if ($needsSort) {
    usort($points, static fn(array $a, array $b): int => $a[0] <=> $b[0]);
}

$firstObserved = $points[0][0];
$lastObserved = $points[array_key_last($points)][0];
$totalSpanMinutes = intdiv($lastObserved - $firstObserved, 60) + 1;

$windows = [
    ['1 day', 1],
    ['7 days', 7],
    ['14 days', 14],
    ['30 days', 30],
    ['90 days', 90],
    ['6 months', 183],
    ['1 year', 365],
];

echo "CGM Summary\n";
echo "===========\n";
echo "Source:        {$file}\n";
echo "First reading: " . fmtTs($firstObserved) . " UTC\n";
echo "Last reading:  " . fmtTs($lastObserved) . " UTC\n";
echo "Elapsed span:  " . fmtDuration($totalSpanMinutes) . "\n";
echo "Gap rule:      >" . MAX_GAP_MINUTES . " missing minutes breaks continuity\n";
echo "\n";

foreach ($windows as [$label, $days]) {
    $expected = $days * 1440;

    if ($totalSpanMinutes < $expected) {
        printf(
            "%-11s skipped (only %s of elapsed history available)\n\n",
            $label . ':',
            fmtDuration($totalSpanMinutes)
        );
        continue;
    }

    $startTs = $lastObserved - (($expected - 1) * 60);
    $from = lowerBound($points, $startTs);
    $to = count($points);

    $count = 0;
    $sum = 0.0;
    $sumSq = 0.0;

    $in70_180 = 0;
    $in70_160 = 0;
    $in70_140 = 0;
    $above180 = 0;
    $above250 = 0;
    $below70 = 0;
    $below54 = 0;

    for ($i = $from; $i < $to; $i++) {
        $v = $points[$i][1];

        $count++;
        $sum += $v;
        $sumSq += $v * $v;

        if ($v >= 70 && $v <= 180) $in70_180++;
        if ($v >= 70 && $v <= 160) $in70_160++;
        if ($v >= 70 && $v <= 140) $in70_140++;
        if ($v > 180) $above180++;
        if ($v > 250) $above250++;
        if ($v < 70) $below70++;
        if ($v < 54) $below54++;
    }

    $mean = $count > 0 ? $sum / $count : NAN;
    $variance = $count > 0 ? max(0.0, ($sumSq / $count) - ($mean * $mean)) : NAN;
    $sd = sqrt($variance);
    $cv = ($count > 0 && $mean > 0) ? ($sd / $mean) * 100.0 : NAN;

    // GMI (%) = 3.31 + 0.02392 × mean glucose (mg/dL)
    $gmi = $count > 0 ? 3.31 + (0.02392 * $mean) : NAN;

    $streaks = thresholdStreaks($points, $from, $to);
    $steady = bestSteadyInRange($points, $from, $to);

    echo str_repeat('=', 76) . "\n";
    echo strtoupper($label) . " SUMMARY\n";
    echo fmtTs($startTs) . " -> " . fmtTs($lastObserved) . " UTC\n";
    echo str_repeat('-', 76) . "\n";

    printf(
        "Observed data: %s / %s (%s coverage)\n",
        fmtDuration($count),
        fmtDuration($expected),
        pct($count, $expected)
    );
    printf("Mean glucose:  %.1f mg/dL\n", $mean);
    printf("GMI:           %.2f%%\n", $gmi);
    printf("Std dev:       %.1f mg/dL\n", $sd);
    printf("CV:            %.1f%%\n", $cv);

    echo "\nRanges\n";
    printf("  %-22s %8s  (%s)\n", "70-180 mg/dL:", pct($in70_180, $count), fmtDuration($in70_180));
    printf("  %-22s %8s  (%s)\n", "70-160 mg/dL:", pct($in70_160, $count), fmtDuration($in70_160));
    printf("  %-22s %8s  (%s)\n", "70-140 mg/dL:", pct($in70_140, $count), fmtDuration($in70_140));
    printf("  %-22s %8s  (%s)\n", ">180 mg/dL:", pct($above180, $count), fmtDuration($above180));
    printf("  %-22s %8s  (%s)\n", ">250 mg/dL:", pct($above250, $count), fmtDuration($above250));
    printf("  %-22s %8s  (%s)\n", "<70 mg/dL:", pct($below70, $count), fmtDuration($below70));
    printf("  %-22s %8s  (%s)\n", "<54 mg/dL:", pct($below54, $count), fmtDuration($below54));

    echo "\nLongest continuous streaks\n";
    printStreak("70-180 mg/dL", $streaks['70-180']);
    printStreak("70-160 mg/dL", $streaks['70-160']);
    printStreak("70-140 mg/dL", $streaks['70-140']);
    printStreak("<=180 mg/dL", $streaks['<=180']);

    echo "\nBest stable in-range plateau (±" . STEADY_TOLERANCE . " mg/dL anchor tolerance)\n";
    if ($steady === null) {
        echo "  n/a\n";
    } else {
        printf(
            "  %s  %s -> %s  range %d-%d, anchor %d, ±actual %d\n",
            fmtDuration($steady['minutes']),
            fmtTs($steady['start']),
            fmtTs($steady['end']),
            $steady['min'],
            $steady['max'],
            $steady['center'],
            $steady['actual']
        );
    }

    echo "\n";
}
