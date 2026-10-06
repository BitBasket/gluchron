<?php

declare(strict_types=1);

namespace App\Tests\Unit;

use PHPUnit\Framework\TestCase;

final class FetchHistoricalDataScriptTest extends TestCase
{
    public function testDownloadUrlRejectsHttpAndDoesNotCreateCsv(): void
    {
        $out = tempnam(sys_get_temp_dir(), 'gluchron-history-');
        self::assertIsString($out);
        unlink($out);

        $result = $this->runScript(['--download-url', 'http://example.test/file.csv', '--out', $out]);

        self::assertNotSame(0, $result['code']);
        self::assertStringContainsString('valid HTTPS URL', $result['stderr']);
        self::assertFileDoesNotExist($out . '.csv');
    }

    public function testDownloadUrlCannotBeCombinedWithExtractionOptions(): void
    {
        $out = tempnam(sys_get_temp_dir(), 'gluchron-history-');
        self::assertIsString($out);
        unlink($out);

        $result = $this->runScript([
            '--download-url', 'https://example.test/file.csv',
            '--from', '2026-01-01',
            '--out', $out,
        ]);

        self::assertNotSame(0, $result['code']);
        self::assertStringContainsString('not supported with --download-url', $result['stderr']);
        self::assertFileDoesNotExist($out . '.csv');
    }

    public function testMissingInteractiveInputFailsExplicitly(): void
    {
        $out = tempnam(sys_get_temp_dir(), 'gluchron-history-');
        self::assertIsString($out);
        unlink($out);

        $result = $this->runScript([], "", ['LIBREVIEW_EMAIL' => '', 'LIBREVIEW_PASSWORD' => '']);

        self::assertNotSame(0, $result['code']);
        self::assertStringContainsString('Interactive input ended unexpectedly', $result['stderr']);
    }

    /** @param list<string> $arguments @param array<string, string> $environment */
    private function runScript(array $arguments, string $stdin = '', array $environment = []): array
    {
        $command = array_merge([PHP_BINARY, dirname(__DIR__, 2) . '/bin/fetch-historical-data.php'], $arguments);
        $pipes = [];
        $process = proc_open($command, [
            0 => ['pipe', 'r'],
            1 => ['pipe', 'w'],
            2 => ['pipe', 'w'],
        ], $pipes, dirname(__DIR__, 2), array_merge($_ENV, $environment));
        self::assertIsResource($process);
        fwrite($pipes[0], $stdin);
        fclose($pipes[0]);
        $stdout = stream_get_contents($pipes[1]);
        $stderr = stream_get_contents($pipes[2]);
        fclose($pipes[1]);
        fclose($pipes[2]);

        return ['code' => proc_close($process), 'stdout' => $stdout, 'stderr' => $stderr];
    }
}
