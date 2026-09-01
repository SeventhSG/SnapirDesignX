#import "SdxpImport.h"

#import <UniformTypeIdentifiers/UniformTypeIdentifiers.h>

@interface SnapirSdxpImport () <UIDocumentPickerDelegate>
@property(nonatomic, copy) void (^completion)(NSString *);
/// The picker holds only a weak delegate, so the importer keeps itself alive
/// until exactly one of the delegate callbacks has run.
@property(nonatomic, strong) SnapirSdxpImport *selfRef;
@end

@implementation SnapirSdxpImport

+ (void)presentFrom:(UIViewController *)host
         completion:(void (^)(NSString *))completion {
  SnapirSdxpImport *importer = [[SnapirSdxpImport alloc] init];
  importer.completion = completion;
  importer.selfRef = importer;

  UIDocumentPickerViewController *picker = [[UIDocumentPickerViewController alloc]
      initForOpeningContentTypes:@[ UTTypeData ]];
  picker.delegate = importer;
  picker.allowsMultipleSelection = NO;

  // On iPad a picker without a presentation anchor is a crash, not a warning.
  picker.modalPresentationStyle = UIModalPresentationFormSheet;
  [host presentViewController:picker animated:YES completion:nil];
}

- (void)finishWith:(NSString *)path {
  void (^done)(NSString *) = self.completion;
  self.completion = nil;
  if (done) {
    dispatch_async(dispatch_get_main_queue(), ^{
      done(path);
    });
  }
  self.selfRef = nil;
}

- (void)documentPicker:(UIDocumentPickerViewController *)controller
    didPickDocumentsAtURLs:(NSArray<NSURL *> *)urls {
  NSURL *source = urls.firstObject;
  if (!source) {
    [self finishWith:nil];
    return;
  }

  // The copy is off the main thread: the picked file can be on a network
  // provider even though it never runs more than a survey's worth of data.
  dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
    [self copyIn:source];
  });
}

- (void)documentPickerWasCancelled:(UIDocumentPickerViewController *)controller {
  [self finishWith:nil];
}

- (void)copyIn:(NSURL *)source {
  const BOOL scoped = [source startAccessingSecurityScopedResource];
  NSFileManager *fm = NSFileManager.defaultManager;

  NSString *name = source.lastPathComponent.length ? source.lastPathComponent
                                                    : @"project.sdxp";
  // A fresh directory per import, so two imports never collide on name.
  NSString *dir =
      [NSTemporaryDirectory() stringByAppendingPathComponent:[NSUUID UUID].UUIDString];
  [fm createDirectoryAtPath:dir withIntermediateDirectories:YES attributes:nil error:nil];
  NSString *dest = [dir stringByAppendingPathComponent:name];

  NSError *err = nil;
  const BOOL ok = [fm copyItemAtURL:source
                              toURL:[NSURL fileURLWithPath:dest]
                              error:&err];
  if (scoped) [source stopAccessingSecurityScopedResource];

  if (!ok) {
    NSLog(@"snapir: could not import %@ -- %@", source.path, err);
    [self finishWith:nil];
    return;
  }
  [self finishWith:dest];
}

@end
