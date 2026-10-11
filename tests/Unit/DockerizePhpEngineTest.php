<?php

declare(strict_types=1);

namespace App\Tests\Unit;

use PHPUnit\Framework\TestCase;

final class DockerizePhpEngineTest extends TestCase
{
    public function testDockerfileUsesPhpexpertsPhpNotDebianCli(): void
    {
        $dockerfile = (string) file_get_contents($this->root() . '/Dockerfile');

        $this->assertStringContainsString('FROM phpexperts/php:', $dockerfile);
        $this->assertStringContainsString('https://raw.githubusercontent.com/PHPExpertsInc/dockerize/v15.x/dockerize.sh', $dockerfile);
        $this->assertStringContainsString('/etc/ssl/certs/ca-certificates.crt', $dockerfile);
        $this->assertStringNotContainsString('php:8.4-cli-bookworm', $dockerfile);
        $this->assertDoesNotMatchRegularExpression('/^FROM php:/m', $dockerfile);
    }

    public function testComposePollerIsDockerizePhpWithCaddyInFront(): void
    {
        $compose = (string) file_get_contents($this->root() . '/docker-compose.yaml');

        $this->assertStringContainsString('PHP_VERSION: ${PHP_VERSION:-8.4}', $compose);
        $this->assertStringContainsString('image: caddy:2-alpine', $compose);
        $this->assertStringContainsString('.:/workdir', $compose);
        $this->assertStringNotContainsString('php:8.4-cli-bookworm', $compose);
        $this->assertStringNotContainsString('phpexperts/web:', $compose);
    }

    public function testEnvExampleSelectsDockerizePhp84(): void
    {
        $env = (string) file_get_contents($this->root() . '/.env.example');

        $this->assertMatchesRegularExpression('/^PHP_VERSION=8\.4$/m', $env);
    }

    private function root(): string
    {
        return dirname(__DIR__, 2);
    }
}
