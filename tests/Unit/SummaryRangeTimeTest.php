<?php

declare(strict_types=1);

namespace App\Tests\Unit;

use PHPUnit\Framework\TestCase;

require_once dirname(__DIR__, 2) . '/bin/summary.php';

final class SummaryRangeTimeTest extends TestCase
{
    public function testStoredReadingsCountAsOneMinuteEach(): void
    {
        $t = gmmktime(8, 0, 0, 10, 5, 2026);
        $points = [
            [$t, 100],
            [$t + 60, 150],
            [$t + 120, 190],
        ];

        $ranges = rangeClockMinutes($points, 0, 3, $t, $t + 120);

        $this->assertSame(3, $ranges['classified']);
        $this->assertSame(2, $ranges['in70_180']);
        $this->assertSame(2, $ranges['in70_160']);
        $this->assertSame(1, $ranges['in70_140']);
        $this->assertSame(1, $ranges['above180']);
        $this->assertSame(0, $ranges['above250']);
    }

    public function testShortGapInsideOneRangeFillsClockTimeAcrossMidnight(): void
    {
        $day = gmmktime(0, 0, 0, 10, 5, 2026);
        $next = gmmktime(0, 0, 0, 10, 6, 2026);
        $points = [
            [$day + (1438 * 60), 120],
            [$next + (2 * 60), 118],
        ];

        $ranges = rangeClockMinutes($points, 0, 2, $points[0][0], $points[1][0]);

        // 23:58, 23:59, 00:00, 00:01, 00:02.
        $this->assertSame(5, $ranges['classified']);
        $this->assertSame(5, $ranges['in70_180']);
        $this->assertSame(5, $ranges['in70_160']);
        $this->assertSame(5, $ranges['in70_140']);
    }

    public function testGapAcross70Or180IsOmitted(): void
    {
        $t = gmmktime(8, 0, 0, 10, 5, 2026);
        $points = [
            [$t, 160],
            [$t + (10 * 60), 190],
        ];

        $ranges = rangeClockMinutes($points, 0, 2, $t, $t + (10 * 60));

        $this->assertSame(2, $ranges['classified']);
        $this->assertSame(1, $ranges['in70_180']);
        $this->assertSame(1, $ranges['above180']);
    }

    public function testGapFillsOnlyTheRangesBothReadingsShare(): void
    {
        $t = gmmktime(8, 0, 0, 10, 5, 2026);
        $points = [
            [$t, 130],
            [$t + (6 * 60), 155],
        ];

        $ranges = rangeClockMinutes($points, 0, 2, $t, $t + (6 * 60));

        // Two readings plus five missing minutes.
        $this->assertSame(7, $ranges['classified']);
        $this->assertSame(7, $ranges['in70_180']);
        $this->assertSame(7, $ranges['in70_160']);
        $this->assertSame(1, $ranges['in70_140']);
    }

    public function testGapLongerThanTwentyMinutesIsOmitted(): void
    {
        $t = gmmktime(8, 0, 0, 10, 5, 2026);
        $points = [
            [$t, 110],
            [$t + (22 * 60), 112],
        ];

        $ranges = rangeClockMinutes($points, 0, 2, $t, $t + (22 * 60));

        $this->assertSame(2, $ranges['classified']);
        $this->assertSame(2, $ranges['in70_140']);
    }

    public function testWindowOpeningInsideAGapCountsOnlyMinutesInsideTheWindow(): void
    {
        $t = gmmktime(8, 0, 0, 10, 5, 2026);
        $points = [
            [$t, 110],
            [$t + (10 * 60), 112],
        ];
        $start = $t + (4 * 60);

        $ranges = rangeClockMinutes($points, 1, 2, $start, $t + (10 * 60));

        // 08:04 through 08:09 from the previous reading, plus 08:10.
        $this->assertSame(7, $ranges['classified']);
        $this->assertSame(7, $ranges['in70_140']);
        $this->assertSame(0, $ranges['above180']);
    }

    public function testVeryHighAndVeryLowGapsNeedBothReadingsInTheTighterBin(): void
    {
        $t = gmmktime(8, 0, 0, 10, 5, 2026);
        $high = rangeClockMinutes([
            [$t, 260],
            [$t + (3 * 60), 240],
        ], 0, 2, $t, $t + (3 * 60));
        $low = rangeClockMinutes([
            [$t, 50],
            [$t + (3 * 60), 60],
        ], 0, 2, $t, $t + (3 * 60));

        $this->assertSame(4, $high['classified']);
        $this->assertSame(4, $high['above180']);
        $this->assertSame(1, $high['above250']);
        $this->assertSame(4, $low['classified']);
        $this->assertSame(4, $low['below70']);
        $this->assertSame(1, $low['below54']);
    }
}
