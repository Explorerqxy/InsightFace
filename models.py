import torch.nn.functional as F
import torchvision
from torch import nn
from torchsummary import summary
from torchvision import transforms

from config import *

# Data augmentation and normalization for training
# Just normalization for validation
data_transforms = {
    'train': transforms.Compose([
        transforms.RandomHorizontalFlip(),
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
    ]),
    'val': transforms.Compose([
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
    ]),
}


class ArcFaceModel(nn.Module):
    def __init__(self):
        super(ArcFaceModel, self).__init__()

        resnet = torchvision.models.resnet50(pretrained=True)

        # Remove linear and pool layers (since we're not doing classification)
        modules = list(resnet.children())[:-1]
        self.resnet = nn.Sequential(*modules)
        self.pool = nn.AvgPool2d(4)
        self.fc1 = nn.Linear(512, 512)
        self.age_pred = nn.Linear(512, 1)

        self.fc2 = nn.Linear(512, 512)
        self.gen_pred = nn.Linear(512, gen_num_classes)

        nn.init.xavier_uniform_(self.age_pred.weight)
        nn.init.xavier_uniform_(self.gen_pred.weight)

    def forward(self, images):
        x = self.resnet(images)  # [N, 512, 1, 1]
        x = self.pool(x)
        x = x.view(-1, 512)  # [N, 512]

        age_out = F.relu(self.fc1(x))  # [N, 512]
        age_out = self.age_pred(age_out)  # [N, 1]

        gen_out = F.relu(self.fc2(x))  # [N, 512]
        gen_out = F.softmax(self.gen_pred(gen_out), dim=1)  # [N, 2]

        return age_out, gen_out


if __name__ == "__main__":
    model = ArcFaceModel().to(device)
    summary(model, (3, 112, 112))