from datetime import datetime

import numpy as np
import torch
from tensorboardX import SummaryWriter
from torch import nn
from torch.optim.lr_scheduler import StepLR

from config import device, num_workers, grad_clip, print_freq
from data_gen import ArcFaceDataset
from focal_loss import FocalLoss
from lfw_eval import lfw_test
from models import ArcFaceModel18, ArcFaceModel34, ArcFaceModel50, ArcFaceModel101, ArcMarginModel
from utils import parse_args, save_checkpoint, AverageMeter, clip_gradient, accuracy


def train_net(args):
    torch.manual_seed(7)
    np.random.seed(7)
    checkpoint = None
    start_epoch = 0
    best_acc = 0
    writer = SummaryWriter()
    epochs_since_improvement = 0

    # Initialize / load checkpoint
    if checkpoint is None:
        if args.network == 'r100':
            model = ArcFaceModel101(args)
        elif args.network == 'r50':
            model = ArcFaceModel50(args)
        elif args.network == 'r34':
            model = ArcFaceModel34(args)
        elif args.network == 'r18':
            model = ArcFaceModel18(args)
        else:
            model = ArcFaceModel50(args)
        model = nn.DataParallel(model)
        metric_fc = ArcMarginModel(args)
        metric_fc = nn.DataParallel(metric_fc)

        if args.optimizer == 'sgd':
            optimizer = torch.optim.SGD([{'params': model.parameters()}, {'params': metric_fc.parameters()}],
                                        lr=args.lr, momentum=args.mom, weight_decay=args.weight_decay)
        else:
            optimizer = torch.optim.Adam([{'params': model.parameters()}, {'params': metric_fc.parameters()}],
                                         lr=args.lr, weight_decay=args.weight_decay)

    else:
        checkpoint = torch.load(checkpoint)
        start_epoch = checkpoint['epoch'] + 1
        epochs_since_improvement = checkpoint['epochs_since_improvement']
        model = checkpoint['model']
        model = nn.DataParallel(model)
        metric_fc = checkpoint['metric_fc']
        metric_fc = nn.DataParallel(metric_fc)
        optimizer = checkpoint['optimizer']

    # Move to GPU, if available
    model = model.to(device)
    metric_fc = metric_fc.to(device)

    # Loss function
    if args.focal_loss:
        criterion = FocalLoss(gamma=args.gamma).to(device)
    else:
        criterion = nn.CrossEntropyLoss().to(device)

    # Custom dataloaders
    train_dataset = ArcFaceDataset('train')
    train_loader = torch.utils.data.DataLoader(train_dataset, batch_size=args.batch_size, shuffle=True,
                                               num_workers=num_workers,
                                               pin_memory=True)

    scheduler = StepLR(optimizer, step_size=args.lr_step, gamma=0.1)

    # Epochs
    for epoch in range(start_epoch, args.end_epoch):
        scheduler.step()

        start = datetime.now()
        # One epoch's training
        train_loss, train_top5_accs = train(train_loader=train_loader,
                                            model=model,
                                            metric_fc=metric_fc,
                                            criterion=criterion,
                                            optimizer=optimizer,
                                            epoch=epoch)
        # train_dataset.shuffle()
        writer.add_scalar('Train Loss', train_loss, epoch)
        writer.add_scalar('Train Top5 Accuracy', train_top5_accs, epoch)

        end = datetime.now()
        delta = end - start
        print('{} seconds'.format(delta.seconds))

        # One epoch's validation
        if epoch > 10 and epoch % 2 == 0:
            start = datetime.now()
            lfw_acc, threshold = lfw_test(model)
            writer.add_scalar('LFW Accuracy', lfw_acc, epoch)

            # Check if there was an improvement
            is_best = lfw_acc > best_acc
            best_acc = max(lfw_acc, best_acc)
            if not is_best:
                epochs_since_improvement += 1
                print("\nEpochs since last improvement: %d\n" % (epochs_since_improvement,))
            else:
                epochs_since_improvement = 0

            # Save checkpoint
            save_checkpoint(epoch, epochs_since_improvement, model, metric_fc, optimizer, best_acc, is_best)

            end = datetime.now()
            delta = end - start
            print('{} seconds'.format(delta.seconds))


def train(train_loader, model, metric_fc, criterion, optimizer, epoch):
    model.train()  # train mode (dropout and batchnorm is used)
    metric_fc.train()

    losses = AverageMeter()
    top5_accs = AverageMeter()

    # Batches
    for i, (img, label) in enumerate(train_loader):
        # Move to GPU, if available
        img = img.to(device)
        label = label.to(device)  # [N, 1]
        # print('class_id_true.size(): ' + str(class_id_true.size()))

        # Forward prop.
        feature = model(img)  # embedding => [N, 512]
        # print('embedding.size(): ' + str(embedding.size()))
        output = metric_fc(feature, label)  # class_id_out => [N, 10575]
        # print('class_id_out.size(): ' + str(class_id_out.size()))

        # Calculate loss
        loss = criterion(output, label)

        # Back prop.
        optimizer.zero_grad()
        loss.backward()

        # Clip gradients
        clip_gradient(optimizer, grad_clip)

        # Update weights
        optimizer.step()

        # Keep track of metrics
        losses.update(loss.item())
        top5_accuracy = accuracy(output, label, 5)
        top5_accs.update(top5_accuracy)

        # Print status
        if i % print_freq == 0:
            print('Epoch: [{0}][{1}/{2}]\t'
                  'Loss {loss.val:.4f} ({loss.avg:.4f})\t'
                  'Top5 Accuracy {top5_accs.val:.3f} ({top5_accs.avg:.3f})'.format(epoch, i, len(train_loader),
                                                                                   loss=losses,
                                                                                   top5_accs=top5_accs))

    return losses.avg, top5_accs.avg


def main():
    global args
    args = parse_args()
    train_net(args)


if __name__ == '__main__':
    main()
