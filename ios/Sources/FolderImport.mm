#import "FolderImport.h"

#import <UniformTypeIdentifiers/UniformTypeIdentifiers.h>

#import "NativeService.h"

@interface SnapirFolderImport () <UIDocumentPickerDelegate>
@property(nonatomic, copy) void (^completion)(NSString *);
/// The picker holds only a weak delegate, so the importer keeps itself alive
/// until exactly one of the delegate callbacks has run.
@property(nonatomic, strong) SnapirFolderImport *selfRef;
@end

@implementation SnapirFolderImport

+ (void)presentFrom:(UIViewController *)host
         completion:(void (^)(NSString *))completion {
  SnapirFolderImport *importer = [[SnapirFolderImport alloc] init];
  importer.completion = completion;
  importer.selfRef = importer;

  UIDocumentPickerViewController *picker = [[UIDocumentPickerViewController alloc]
      initForOpeningContentTypes:@[ UTTypeFolder ]];
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

  // The copy is off the main thread: a survey folder is small, but it is the
  // operator's storage and it can be a network provider.
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
                                                   : @"survey";
  NSString *dest =
      [SnapirNativeService.surveysDirectory stringByAppendingPathComponent:name];

  NSError *err = nil;
  // Re-importing the same job replaces it. Merging two copies of a survey
  // would leave rooms from both in one folder, which is worse than losing the
  // older import.
  if ([fm fileExistsAtPath:dest]) [fm removeItemAtPath:dest error:nil];

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
