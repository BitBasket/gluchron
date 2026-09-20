<?php

declare(strict_types=1);

namespace App\Tests\Unit;

use App\Http\CloudMigrateClient;
use App\Http\Kernel;
use PHPUnit\Framework\TestCase;

final class CloudMigrateClientTest extends TestCase
{
    public function testPostsPublicKeyAndCiphertextNeverPrivateKey(): void
    {
        $root = $this->fixture();
        $posts = [];
        $http = function (string $method, string $url, string $body) use (&$posts): array {
            $posts[] = ['method' => $method, 'url' => $url, 'body' => $body];
            $this->assertStringNotContainsString('BEGIN PGP PRIVATE KEY', $body);
            if (str_ends_with($url, '/api/self-host-migrate')) {
                return ['status' => 201, 'body' => json_encode([
                    'ok' => true,
                    'id' => 'abcdefghijklmnopqrstuv',
                    'path' => '/t/abcdefghijklmnopqrstuv/',
                    'importedBuckets' => 1,
                ], JSON_THROW_ON_ERROR)];
            }

            return ['status' => 200, 'body' => json_encode([
                'ok' => true,
                'importedBuckets' => 1,
            ], JSON_THROW_ON_ERROR)];
        };

        $client = new CloudMigrateClient(
            $root . '/public',
            $root . '/data/keys/user-public.asc',
            $root . '/data/poll-state.json',
            'https://cloud.example',
            $http,
            1,
        );

        $result = $client->handle($this->loopback(), '');
        $this->assertSame(201, $result['status']);
        $payload = json_decode($result['body'], true, 512, JSON_THROW_ON_ERROR);
        $this->assertTrue($payload['ok']);
        $this->assertSame('https://cloud.example/t/abcdefghijklmnopqrstuv/', $payload['url']);
        $this->assertSame(2, $payload['importedBuckets']);
        $this->assertCount(2, $posts);
        $this->assertSame('https://cloud.example/api/self-host-migrate', $posts[0]['url']);
        $this->assertSame('https://cloud.example/t/abcdefghijklmnopqrstuv/api/import', $posts[1]['url']);

        $first = json_decode($posts[0]['body'], true, 512, JSON_THROW_ON_ERROR);
        $this->assertSame('mylibre.self-host-migrate', $first['schema']);
        $this->assertStringContainsString('BEGIN PGP PUBLIC KEY', $first['publicKey']);
        $this->assertArrayHasKey('100', $first['buckets']);
        $this->assertSame(50, $first['pollState']['firstReadingAt']);
        $second = json_decode($posts[1]['body'], true, 512, JSON_THROW_ON_ERROR);
        $this->assertArrayHasKey('200', $second['buckets']);
        $this->assertArrayNotHasKey('100', $second['buckets']);
    }

    public function testRequiresCloudUrl(): void
    {
        $root = $this->fixture();
        $client = new CloudMigrateClient(
            $root . '/public',
            $root . '/data/keys/user-public.asc',
            $root . '/data/poll-state.json',
            '',
            static fn (): array => ['status' => 500, 'body' => ''],
        );
        $result = $client->handle($this->loopback(), '');
        $this->assertSame(503, $result['status']);
    }

    public function testRequiresEnrolledPublicKey(): void
    {
        $root = $this->fixture();
        unlink($root . '/data/keys/user-public.asc');
        $client = new CloudMigrateClient(
            $root . '/public',
            $root . '/data/keys/user-public.asc',
            $root . '/data/poll-state.json',
            'https://cloud.example',
            static fn (): array => ['status' => 500, 'body' => ''],
        );
        $result = $client->handle($this->loopback(), '');
        $this->assertSame(400, $result['status']);
    }

    public function testFrontDoorLeavesTenantsOnTheEngine(): void
    {
        $dir = sys_get_temp_dir() . '/mylibre-front-' . uniqid('', true);
        mkdir($dir . '/public', 0700, true);
        $kernel = new Kernel($dir . '/public', '', new \App\Http\KeyEnrollmentHandler($dir . '/user-public.asc'));
        $client = new CloudMigrateClient(
            $dir . '/public',
            $dir . '/user-public.asc',
            $dir . '/poll-state.json',
            'https://cloud.example',
            static fn (): array => ['status' => 500, 'body' => ''],
        );
        $front = new \App\Http\SelfHostFront($kernel, $client);
        $result = $front->handle([
            'REQUEST_METHOD' => 'POST',
            'REQUEST_URI' => '/api/tenants',
            'REMOTE_ADDR' => '127.0.0.1',
            'HTTP_HOST' => '127.0.0.1:8765',
        ], '{}');
        $this->assertSame(404, $result['status']);
    }

    public function testHttpsRequired(): void
    {
        $root = $this->fixture();
        $client = new CloudMigrateClient(
            $root . '/public',
            $root . '/data/keys/user-public.asc',
            $root . '/data/poll-state.json',
            'https://cloud.example',
            static fn (): array => ['status' => 500, 'body' => ''],
        );
        $result = $client->handle([
            'REQUEST_METHOD' => 'POST',
            'REQUEST_URI' => '/api/migrate-to-cloud',
            'REMOTE_ADDR' => '203.0.113.9',
            'HTTP_HOST' => 'home.example',
        ], '');
        $this->assertSame(403, $result['status']);
        $this->assertFalse(Kernel::allowsCredentialPost([
            'REMOTE_ADDR' => '203.0.113.9',
            'HTTP_HOST' => 'home.example',
        ]));
    }

    /**
     * @return array<string, string>
     */
    private function loopback(): array
    {
        return [
            'REQUEST_METHOD' => 'POST',
            'REQUEST_URI' => '/api/migrate-to-cloud',
            'REMOTE_ADDR' => '127.0.0.1',
            'HTTP_HOST' => '127.0.0.1:8765',
        ];
    }

    private function fixture(): string
    {
        $root = sys_get_temp_dir() . '/mylibre-cloud-client-' . uniqid('', true);
        mkdir($root . '/public/b', 0700, true);
        mkdir($root . '/data/keys', 0700, true);
        file_put_contents($root . '/data/keys/user-public.asc', "-----BEGIN PGP PUBLIC KEY BLOCK-----\npub\n-----END PGP PUBLIC KEY BLOCK-----\n");
        file_put_contents($root . '/data/keys/private.asc', "-----BEGIN PGP PRIVATE KEY BLOCK-----\nsecret\n-----END PGP PRIVATE KEY BLOCK-----\n");
        file_put_contents($root . '/public/current.json.asc', "-----BEGIN PGP MESSAGE-----\ncur\n-----END PGP MESSAGE-----\n");
        file_put_contents($root . '/data/poll-state.json', json_encode([
            'seen' => [1],
            'firstReadingAt' => 50,
        ], JSON_THROW_ON_ERROR));
        file_put_contents($root . '/public/b/100.json.asc', "-----BEGIN PGP MESSAGE-----\none\n-----END PGP MESSAGE-----\n");
        file_put_contents($root . '/public/b/200.json.asc', "-----BEGIN PGP MESSAGE-----\ntwo\n-----END PGP MESSAGE-----\n");

        return $root;
    }
}
