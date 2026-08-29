#import "NativeService.h"

#include <atomic>
#include <cstdlib>
#include <string>
#include <thread>

#include <netinet/in.h>
#include <sys/socket.h>
#include <unistd.h>

#include "snapir/service.hpp"

namespace {

std::atomic<bool> g_started{false};

}  // namespace

@implementation SnapirNativeService

+ (NSInteger)port {
  return 8765;
}

+ (NSString *)origin {
  return [NSString stringWithFormat:@"http://127.0.0.1:%ld", (long)self.port];
}

+ (NSString *)documentsDirectory {
  return NSSearchPathForDirectoriesInDomains(NSDocumentDirectory,
                                             NSUserDomainMask, YES)
      .firstObject;
}

+ (NSString *)surveysDirectory {
  NSString *dir = [[self documentsDirectory] stringByAppendingPathComponent:@"surveys"];
  [[NSFileManager defaultManager] createDirectoryAtPath:dir
                            withIntermediateDirectories:YES
                                             attributes:nil
                                                  error:nil];
  return dir;
}

+ (BOOL)startReturningError:(NSString **)error {
  if (g_started.exchange(true)) return YES;  // one service per process

  // The interface ships in the bundle already unpacked, at a real readable
  // path, so unlike the APK there is nothing to copy out before serving it.
  NSString *webRoot =
      [NSBundle.mainBundle.resourcePath stringByAppendingPathComponent:@"web"];
  BOOL isDir = NO;
  if (![NSFileManager.defaultManager fileExistsAtPath:webRoot isDirectory:&isDir] ||
      !isDir) {
    g_started = false;
    if (error) *error = [NSString stringWithFormat:@"No interface at %@", webRoot];
    return NO;
  }

  // store.cpp reads APPDATA and then falls back to HOME + "/.config". iOS does
  // set HOME, to the container root, so without this the settings and the
  // project list land in a hidden directory at the top of the container where
  // nothing expects them and nothing backs them up.
  NSString *support = NSSearchPathForDirectoriesInDomains(
                          NSApplicationSupportDirectory, NSUserDomainMask, YES)
                          .firstObject;
  [NSFileManager.defaultManager createDirectoryAtPath:support
                          withIntermediateDirectories:YES
                                           attributes:nil
                                                error:nil];
  setenv("HOME", support.fileSystemRepresentation, 1);

  const std::string root = webRoot.fileSystemRepresentation;
  const int p = static_cast<int>(self.port);

  std::thread([root, p] {
    NSLog(@"snapir: serving %s on 127.0.0.1:%d", root.c_str(), p);
    const int rc = snapir::serve("127.0.0.1", p, root);
    NSLog(@"snapir: service stopped, rc=%d", rc);
    g_started = false;
  }).detach();

  return YES;
}

+ (BOOL)isListening {
  const int fd = socket(AF_INET, SOCK_STREAM, 0);
  if (fd < 0) return NO;

  struct sockaddr_in addr = {};
  addr.sin_family = AF_INET;
  addr.sin_port = htons(static_cast<uint16_t>(self.port));
  addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);

  const BOOL up = connect(fd, reinterpret_cast<struct sockaddr *>(&addr),
                          sizeof(addr)) == 0;
  close(fd);
  return up;
}

+ (BOOL)waitUntilReady:(NSTimeInterval)timeout {
  NSDate *deadline = [NSDate dateWithTimeIntervalSinceNow:timeout];
  while ([deadline timeIntervalSinceNow] > 0) {
    if ([self isListening]) return YES;
    [NSThread sleepForTimeInterval:0.1];
  }
  return NO;
}

@end
